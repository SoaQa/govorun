from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Текст кнопки — используется и для отображения, и для распознавания нажатия
WRITE_AUTHOR_BTN = "\u2709\ufe0f Write to author"


def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура с кнопкой 'Написать автору'."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(KeyboardButton(WRITE_AUTHOR_BTN))
    return markup
