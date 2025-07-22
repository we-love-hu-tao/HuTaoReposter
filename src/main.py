import asyncio
import logging
import sys
import uuid

from aiogram import Bot as TgBot
from aiogram import Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums.parse_mode import ParseMode
from aiogram.utils.media_group import MediaGroupBuilder
from loguru import logger
from vkbottle import API as VkAPI
from vkbottle import GroupEventType, GroupTypes, PhotoWallUploader, User
from vkbottle.bot import Bot as VkBot
from vkbottle.bot import MessageEvent, rules
from vkbottle_types.objects import PhotosPhotoSizes

from config import (
    TG_ADMIN_IDS,
    TG_CHANNEL_ID,
    TG_TOKEN,
    VK_ADMIN_IDS,
    VK_GROUP_ID,
    VK_GROUP_TOKEN,
    VK_USER_TOKEN,
)
from keyboards import (
    tg_generate_approve_kbd,
    tg_generate_post_link_kbd,
    vk_generate_approve_kbd,
    vk_generate_post_link_kbd,
)
from middlewares import MediaGroupMiddleware

# VK
vk_posts = {}
vk_bot = VkBot(VK_GROUP_TOKEN)
user = User(VK_USER_TOKEN)
uploader = PhotoWallUploader(user.api)

# TG
tg_posts = {}
dp = Dispatcher()
tg_bot = TgBot(TG_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def delete_first_key(dictionary: dict):
    for key in dictionary:
        return dictionary.pop(key, None)
    raise IndexError


# --- AIOgram/TG handlers and functions ---


async def tg_process_files(messages: list[types.Message]) -> dict | str | None:
    """Returns all attachments as bytes in a dictionary

    Args:
        messages (list[types.Message]): List of TG messages with attachments

    Returns:
        dict: Dictionary with separated attachments as bytes and the first caption
        str: Returns only text if there's no files
        None: None of the messages are attachments or text
    """

    # TODO: Currently, we're only processing photos
    files = {
        "photos": [],
        "caption": None
    }

    for message in messages:
        if not message.photo:
            continue

        if message.caption:
            files["caption"] = message.caption

        file_info = await tg_bot.get_file(message.photo[-1].file_id)
        file = await tg_bot.download_file(file_info.file_path)  # type:ignore

        if not file:
            logger.error(f"TG - Couldn't download file at {file_info.file_path}, skipping")
            continue

        files["photos"].append(file.read())

    is_empty = True
    for file in files:
        if file == "caption":
            continue

        if files[file]:
            is_empty = False
            break

    if is_empty:
        return messages[0].text
    return files


async def tg_post(
    bot: TgBot, chat_id: str, text: str | None, files: dict | None
) -> list[types.Message]:
    is_media_empty = True
    if files is not None:
        for attachment in files:
            if attachment == "caption":
                continue

            if files[attachment]:
                is_media_empty = False
                break

    if is_media_empty:
        if text is not None:
            return [(await bot.send_message(chat_id=chat_id, text=text))]
        raise ValueError("TG - No media and no text during a post")

    media_group = MediaGroupBuilder(caption=text)
    for attachment in files:  # type: ignore
        for media in files[attachment]:  # type: ignore
            if attachment == "photos":
                media_group.add_photo(media=media)

    return (await bot.send_media_group(chat_id=chat_id, media=media_group.build()))


async def tg_suggest_post_to(messages: list[types.Message], user_ids: list[int]) -> None:
    suggestion_uuid_hex: str = uuid.uuid4().hex
    tg_posts[suggestion_uuid_hex] = messages

    if len(tg_posts) > 100:
        delete_first_key(tg_posts)

    message_ids: list[int] = [message.message_id for message in messages]
    from_chat_id = messages[0].chat.id

    kbd = tg_generate_approve_kbd(suggestion_uuid_hex)

    for user_id in user_ids:
        if len(messages) > 1:
            await tg_bot.forward_messages(
                chat_id=user_id, from_chat_id=from_chat_id, message_ids=message_ids
            )
        else:
            await tg_bot.forward_message(
                chat_id=user_id, from_chat_id=from_chat_id, message_id=message_ids[0]
            )
        
        await tg_bot.send_message(
            user_id,
            (
                "✅ Новый пост в группе ТГ!"
                "\nХотите запостить его и в ВК?"
            ),
            reply_markup=kbd
        )


async def tg_handle_posting(uuid_hex: str, decision: str, callback_query: types.CallbackQuery):
    try:
        post: list[types.Message] = tg_posts[uuid_hex]
    except KeyError:
        await callback_query.message.edit_text(  # type:ignore
            "❓ Этого поста больше не существует! Возможно, что его уже принял"
            " или проигнорил другой модератор, или пост слишком старый!"
        )
        return

    post_link = f"https://t.me/{post[0].chat.username}/{post[0].message_id}"

    if decision == "approve":
        logger.info(f"TG - Approving post {post_link}")
        await callback_query.message.edit_text(  # type:ignore
            "⏳ Скачиваем и загружаем файлы..."
        )
        files_bytes: dict | str | None = await tg_process_files(post)
        attachments = None
        if isinstance(files_bytes, dict):
            attachments = await vk_upload(files_bytes)
            text = files_bytes["caption"]
        elif isinstance(files_bytes, str):
            text = files_bytes

        await callback_query.message.edit_text(  # type:ignore
            "⏳ Постим в ВК..."
        )
        post_url: str = await vk_post(
            user.api, VK_GROUP_ID, text, attachments
        )

        kbd = tg_generate_post_link_kbd(post_url)
        await callback_query.message.edit_text(  # type:ignore
            "🎉 Ура, новый постик - теперь в ВК!", reply_markup=kbd
        )
    elif decision == "ignore":
        logger.info(f"TG - Ignoring post {post_link}")
        await callback_query.message.edit_text(  # type:ignore
            "✅ Пост успешно проигнорирован!"
        )
    else:
        logger.error(f"TG - Unknown decision on a post {post_link} - {decision}")
        await callback_query.message.edit_text(  # type:ignore
            "⁉️ Эээ, ааа... Можно только принять или проигнорировать пост. Что"
            " ты только что сделал - я честно хз. Чисто на всякий, я удалю этот"
            " пост из очереди, а то мало ли ещё чет сломает..."
        )

    try:
        tg_posts.pop(uuid_hex)
    except KeyError:
        logger.warning(f"TG - Couldn't delete post {uuid_hex} - not found. Bad async?")


@dp.channel_post(F.media_group_id)
async def tg_post_group_media_handler(message: types.Message, album: list[types.Message]):
    # Handle media group posts coming from TG
    # TODO?: Make this a rule

    if str(message.chat.id) != TG_CHANNEL_ID:
        return

    logger.info("TG - New media group post, sending to admins")
    await tg_suggest_post_to(album, TG_ADMIN_IDS)


@dp.channel_post()
async def tg_post_handler(message: types.Message):
    # Handle group posts coming from TG
    # TODO?: Make this a rule

    if str(message.chat.id) != TG_CHANNEL_ID:
        return

    logger.info("TG - New post, sending to admins")
    await tg_suggest_post_to([message], TG_ADMIN_IDS)


@dp.callback_query(F.data.regexp(r"(?:approve|ignore):.+"))
async def tg_post_action_handler(callback_query: types.CallbackQuery):
    if callback_query.data is None:
        logger.error(f"TG - No callback query data: {callback_query}")
        return

    decision, post_uuid_hex = callback_query.data.split(':')
    await tg_handle_posting(post_uuid_hex, decision, callback_query)


# --- VKBottle/VK handlers and functions ---


def vk_pick_img(sizes: list[PhotosPhotoSizes]) -> str | None:
    sizes_w = [photo.width for photo in sizes]
    best_size = max(sizes_w)

    for photo in sizes:
        if photo.width == best_size:
            photo_url = photo.url
            break

    return photo_url


async def vk_process_files(post: GroupTypes.WallPostNew) -> dict | None:
    """Returns all attachments in a social media's format in a dictionary

    Args:
        post (GroupTypes.WallPostNew): VK post with attachments

    Returns:
        dict: Dictionary with separated attachments as urls
        None: No attachments in a post
    """

    # TODO: Currently, we're only processing photos
    files = {
        "photos": [],
    }

    if not post.object.attachments:
        return

    for attachment in post.object.attachments:
        if not attachment.photo:
            continue

        best_size_url = None
        if attachment.photo.sizes:
            best_size_url = vk_pick_img(attachment.photo.sizes)

        if not best_size_url:
            logger.error(f"VK - Couldn't find size for a photo: {attachment.photo}")
            continue

        files["photos"].append(best_size_url)

    is_empty = True
    for file in files:
        if file == "caption":
            continue

        if files[file]:
            is_empty = False
            break

    if is_empty:
        return
    return files


async def vk_upload(files_bytes: dict) -> list[str]:
    # TODO: Currently, we're only processing photos
    attachments: list[str] = []

    for file in files_bytes["photos"]:
        attachment = await uploader.upload(file, VK_GROUP_ID)
        attachments.append(attachment)

    return attachments


async def vk_post(api: VkAPI, group_id: int, text: str, attachments: list[str] | str | None) -> str:
    """Returns link of the post"""
    if isinstance(attachments, str):
        attachments = [attachments]

    post = await api.wall.post(owner_id=-group_id, attachments=attachments, message=text)
    return f"https://vk.com/wall-{group_id}_{post.post_id}"


async def vk_suggest_post_to(post: GroupTypes.WallPostNew, user_ids: list[int]):
    suggestion_uuid_hex: str = uuid.uuid4().hex
    vk_posts[suggestion_uuid_hex] = post

    if len(vk_posts) > 100:
        delete_first_key(vk_posts)

    kbd = vk_generate_approve_kbd(suggestion_uuid_hex)

    await vk_bot.api.messages.send(
        peer_ids=user_ids,
        message=(
            "✅ Новый пост в группе ВК!"
            "\nХотите запостить его и в ТГ?"
        ),
        attachment=f"wall-{VK_GROUP_ID}_{post.object.id}",
        keyboard=kbd,
        random_id=0
    )


async def vk_handle_posting(uuid_hex: str, decision: str, event: MessageEvent):
    try:
        post: GroupTypes.WallPostNew = vk_posts[uuid_hex]
    except KeyError:
        await event.edit_message(  # type:ignore
            "❓ Этого поста больше не существует! Возможно, что его уже принял"
            " или проигнорил другой модератор, или пост слишком старый!"
        )
        return

    post_link = f"https://vk.com/wall{post.object.owner_id}_{post.object.id}"

    if decision == "approve":
        logger.info(
            f"VK - Approving post {post_link}"
        )
        await event.edit_message(  # type:ignore
            "⏳ Скачиваем и загружаем файлы..."
        )
        files: dict | None = await vk_process_files(post)
        text = post.object.text

        await event.edit_message(  # type:ignore
            "⏳ Постим в ТГ..."
        )

        new_tg_post: list[types.Message] = await tg_post(
            tg_bot, TG_CHANNEL_ID, text, files
        )
        chat_username = new_tg_post[0].chat.username
        msg_id = new_tg_post[0].message_id
        tg_post_url = f"https://t.me/{chat_username}/{msg_id}"

        kbd = vk_generate_post_link_kbd(tg_post_url)
        await event.edit_message(  # type:ignore
            "🎉 Ура, новый постик - теперь в ТГ!", keyboard=kbd
        )
    elif decision == "ignore":
        logger.info(f"VK - Ignoring post {post_link}")
        await event.edit_message(  # type:ignore
            "✅ Пост успешно проигнорирован!"
        )
    else:
        logger.error(f"VK - Unknown decision on a post {post_link} - {decision}")
        await event.edit_message(  # type:ignore
            "⁉️ Эээ, ааа... Можно только принять или проигнорировать пост. Что"
            " ты только что сделал - я честно хз. Чисто на всякий, я удалю этот"
            " пост из очереди, а то мало ли ещё чет сломает..."
        )

    try:
        vk_posts.pop(uuid_hex)
    except KeyError:
        logger.warning(f"VK - Couldn't delete post {uuid_hex} - not found. Bad async?")


@vk_bot.on.raw_event(GroupEventType.WALL_POST_NEW, dataclass=GroupTypes.WallPostNew)
async def vk_post_handler(event: GroupTypes.WallPostNew):
    # Handle posts coming from VK - post to TG
    logger.info("VK - New post, sending to admins")
    await vk_suggest_post_to(event, VK_ADMIN_IDS)


@vk_bot.on.raw_event(
    GroupEventType.MESSAGE_EVENT,
    MessageEvent,
    rules.PayloadMapRule([
        ("decision", str),
        ("uuid", str)
    ])
)
async def vk_post_action_handler(event: MessageEvent):
    payload = event.get_payload_json()
    if payload is None:
        logger.error(f"VK - No payload on action: {event}")
        return

    decision, post_uuid_hex = payload["decision"], payload["uuid"]
    await vk_handle_posting(post_uuid_hex, decision, event)


def main():
    loop = asyncio.new_event_loop()
    loop.create_task(vk_bot.run_polling())

    dp.channel_post.middleware(MediaGroupMiddleware())
    loop.create_task(dp.start_polling(tg_bot, allowed_updates=dp.resolve_used_update_types()))

    logger.info("Starting bot")
    tasks = asyncio.all_tasks(loop)
    loop.run_until_complete(asyncio.wait(tasks))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
