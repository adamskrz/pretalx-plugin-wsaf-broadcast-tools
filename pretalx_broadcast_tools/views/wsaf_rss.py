import json
from typing import Any

from django.contrib.syndication.views import Feed
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest
from django.utils.html import escape
from pretalx.event.models import Event
from pretalx.schedule.models import TalkSlot

from pretalx_broadcast_tools.views.wsaf_schedule import WSAFScheduleData


class WSAFRssView(Feed):
    title = "WSAF Schedule for Digital Signage"
    description = "An RSS feed of the schedule for use in digital signage applications like SiteBuilder."
    link = "/"
    request = None  # type: ignore

    def get_object(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Event:
        self.request = request
        return getattr(request, "event", None)

    def items(self, obj: Event):
        schedule_data = WSAFScheduleData(
            event=obj,
            schedule=obj.current_schedule,
        )

        talks: list[TalkSlot] = []
        for day in schedule_data.data:
            for room in day["rooms"]:
                talks.extend(room["talks"])
        return talks

    def item_title(self, item: Any):
        return escape(str(item.submission.title) if item.submission else "No title")

    def item_description(self, item: Any):
        #  "organiser": self.event.organisation.name if self.event.organisation is not None else None,
        #     "title": self.event.title,
        #     "description": self.event.short_description,
        #     "categories": [category.name for category in self.event.categories.all()],
        #     "start": self.start,
        #     "end": self.end,
        #     "venue": self.venue.name,
        #     "image": self.event.image_base64(),
        #     "colour": self.event.primary_category.colour_theme if self.event.primary_category else "PURPLE",
        # }
        talk_details = {
            "title": item.submission.title if item.submission else "No title",
            "speakers": (
                [str(speaker) for speaker in item.submission.speakers.all()]
                if item.submission
                else []
            ),
            "start": item.local_start.isoformat(),
            "end": item.local_end.isoformat(),
            "venue": str(item.room.name),
        }
        json_str = json.dumps(talk_details, cls=DjangoJSONEncoder)
        json_str = json_str.replace(" ", "%20")
        return json_str

    def item_link(self, item: Any):
        return "https://wsaf.org.uk"  # No link, but required by the feed format
