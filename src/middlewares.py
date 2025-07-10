import asyncio

from aiogram import BaseMiddleware, types


class MediaGroupMiddleware(BaseMiddleware):
    ALBUM_DATA: dict[str, list[types.Message]] = {}

    def __init__(self, delay: int | float = 0.6):
        self.delay = delay

    async def __call__(
        self,
        handler,
        event: types.Message,
        data: dict,
    ):
        if not event.media_group_id:
            return await handler(event, data)

        try:
            self.ALBUM_DATA[event.media_group_id].append(event)
            return  # Don't propagate the event
        except KeyError:
            self.ALBUM_DATA[event.media_group_id] = [event]
            await asyncio.sleep(self.delay)
            data["album"] = self.ALBUM_DATA.pop(event.media_group_id)

        return await handler(event, data)
