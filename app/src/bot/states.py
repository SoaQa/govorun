"""
Простая FSM-логика через словарь.
Хранит состояния пользователей в памяти (для MVP достаточно).
"""

# Возможные состояния
STATE_IDLE = "idle"
STATE_WAITING_MESSAGE = "waiting_message"

# user_id -> state
_user_states: dict[int, str] = {}


def get_state(user_id: int) -> str:
    return _user_states.get(user_id, STATE_IDLE)


def set_state(user_id: int, state: str) -> None:
    _user_states[user_id] = state


def reset_state(user_id: int) -> None:
    _user_states.pop(user_id, None)
