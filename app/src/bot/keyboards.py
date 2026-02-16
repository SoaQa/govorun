from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from src.bot.messages import BTN_WRITE


def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура с кнопкой 'Написать автору'."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(KeyboardButton(BTN_WRITE))
    return markup
