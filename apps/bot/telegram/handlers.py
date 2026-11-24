"""Telegram handlers. Thin on purpose: read the update, call apps.bot.services,
render apps.bot.texts. Database work runs in a thread through sync_to_async."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async

from apps.bot import services, texts
from apps.bot.models import Subscription, TelegramUser
from apps.bot.telegram import keyboards
from apps.bot.telegram.callbacks import ShowList, SubscriptionAction
from apps.bot.telegram.states import TargetPriceForm

router = Router(name="pricewatch")
router.message.filter(F.chat.type == "private")


# --- Commands -------------------------------------------------------------------


@router.message(CommandStart())
async def start(message: Message, tg_user: TelegramUser) -> None:
    await message.answer(texts.welcome(tg_user))


@router.message(Command("help"))
async def show_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.CANCELLED)


@router.message(Command("list"))
async def show_list(message: Message, tg_user: TelegramUser) -> None:
    subscriptions = await sync_to_async(services.user_subscriptions)(tg_user)
    await message.answer(
        texts.subscription_list(subscriptions),
        reply_markup=keyboards.list_keyboard(subscriptions),
    )


# --- Messages -------------------------------------------------------------------


@router.message(TargetPriceForm.waiting_for_price, F.text)
async def receive_target_price(message: Message, state: FSMContext, tg_user: TelegramUser) -> None:
    data = await state.get_data()
    try:
        subscription = await sync_to_async(services.set_target_price)(
            tg_user, data["subscription_id"], message.text or ""
        )
    except ValueError:
        await message.answer(texts.BAD_PRICE)
        return
    except Subscription.DoesNotExist:
        await state.clear()
        await message.answer(texts.NOT_FOUND)
        return
    await state.clear()
    await message.answer(
        texts.target_saved(subscription),
        reply_markup=keyboards.back_to_card_keyboard(subscription),
    )


@router.message(F.text.func(services.extract_url))
async def track_link(message: Message, tg_user: TelegramUser) -> None:
    progress = await message.answer(texts.CHECKING)
    url = services.extract_url(message.text) or ""
    try:
        result = await sync_to_async(services.subscribe)(tg_user, url)
    except services.SubscribeError as error:
        await progress.edit_text(texts.subscribe_error(error))
        return
    await progress.edit_text(
        texts.subscribed(result),
        reply_markup=keyboards.subscription_keyboard(result.subscription),
    )


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(texts.SEND_A_LINK)


# --- Buttons --------------------------------------------------------------------


@router.callback_query(ShowList.filter())
async def list_button(callback: CallbackQuery, tg_user: TelegramUser) -> None:
    subscriptions = await sync_to_async(services.user_subscriptions)(tg_user)
    await _show(
        callback, texts.subscription_list(subscriptions), keyboards.list_keyboard(subscriptions)
    )
    await callback.answer()


@router.callback_query(SubscriptionAction.filter(F.action == "open"))
async def open_card(
    callback: CallbackQuery, callback_data: SubscriptionAction, tg_user: TelegramUser
) -> None:
    subscription = await _subscription_or_alert(callback, tg_user, callback_data.id)
    if subscription is None:
        return
    await _show(
        callback,
        texts.card(subscription),
        keyboards.subscription_keyboard(subscription, with_back=True),
    )
    await callback.answer()


@router.callback_query(SubscriptionAction.filter(F.action == "history"))
async def show_history(
    callback: CallbackQuery, callback_data: SubscriptionAction, tg_user: TelegramUser
) -> None:
    subscription = await _subscription_or_alert(callback, tg_user, callback_data.id)
    if subscription is None:
        return
    snapshots = await sync_to_async(services.price_history)(subscription)
    await _show(
        callback,
        texts.history(subscription, snapshots),
        keyboards.back_to_card_keyboard(subscription),
    )
    await callback.answer()


@router.callback_query(SubscriptionAction.filter(F.action == "target"))
async def ask_target(
    callback: CallbackQuery,
    callback_data: SubscriptionAction,
    tg_user: TelegramUser,
    state: FSMContext,
) -> None:
    subscription = await _subscription_or_alert(callback, tg_user, callback_data.id)
    if subscription is None:
        return
    await state.set_state(TargetPriceForm.waiting_for_price)
    await state.update_data(subscription_id=subscription.pk)
    # A new message, so the product card stays on screen above the question.
    await callback.bot.send_message(callback.from_user.id, texts.ask_target(subscription))
    await callback.answer()


@router.callback_query(SubscriptionAction.filter(F.action == "delete"))
async def delete_subscription(
    callback: CallbackQuery, callback_data: SubscriptionAction, tg_user: TelegramUser
) -> None:
    removed = await sync_to_async(services.unsubscribe)(tg_user, callback_data.id)
    if removed is None:
        await callback.answer(texts.NOT_FOUND, show_alert=True)
        return
    await _show(callback, texts.unsubscribed(removed), None)
    await callback.answer()


async def _subscription_or_alert(
    callback: CallbackQuery, tg_user: TelegramUser, subscription_id: int
) -> Subscription | None:
    subscription = await sync_to_async(services.get_subscription)(tg_user, subscription_id)
    if subscription is None:
        await callback.answer(texts.NOT_FOUND, show_alert=True)
    return subscription


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Replace the message the button belongs to; send a new one if it is too old to edit."""
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
        return
    await callback.bot.send_message(callback.from_user.id, text, reply_markup=markup)
