from aiogram.fsm.state import State, StatesGroup


class TargetPriceForm(StatesGroup):
    waiting_for_price = State()  # data: {"subscription_id": int}
