from aiogram.types import InlineKeyboardButton
from aiogram.types.inline_keyboard_markup import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from vkbottle import Callback, Keyboard, OpenLink
from vkbottle import KeyboardButtonColor as Color


# TG keyboards
def tg_generate_approve_kbd(uuid_hex: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="✅ Да", callback_data=f"approve:{uuid_hex}"
            ),
            InlineKeyboardButton(
                text="❌ Нет", callback_data=f"ignore:{uuid_hex}"
            )
        ]
    ]

    keyboard = InlineKeyboardBuilder(buttons)
    return keyboard.as_markup()

def tg_generate_post_link_kbd(link: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="👀 Открыть в ВК", url=link)]]

    keyboard = InlineKeyboardBuilder(buttons)
    return keyboard.as_markup()


# VK keyboards
def vk_generate_approve_kbd(uuid_hex: str) -> str:
    approve_payload = {
        "decision": "approve",
        "uuid": uuid_hex
    }
    ignore_payload = {
        "decision": "ignore",
        "uuid": uuid_hex
    }

    keyboard = (
        Keyboard(inline=True)
        .add(Callback("✅ Да", payload=approve_payload), Color.POSITIVE)
        .add(Callback("❌ Нет", payload=ignore_payload), Color.NEGATIVE)
    ).get_json()
    return keyboard

def vk_generate_post_link_kbd(link: str) -> str:
    keyboard = (
        Keyboard(inline=True)
        .add(OpenLink(link, "👀 Открыть в ТГ"), Color.PRIMARY)
    ).get_json()
    return keyboard
