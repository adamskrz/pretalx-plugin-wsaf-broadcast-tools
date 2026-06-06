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
            "organiser": (
                name_answer.answer
                if (
                    name_answer := item.submission.answers.filter(
                        question__id=item.event.settings.broadcast_tools_wsaf_performer_name
                    ).first()
                )
                else (
                    item.submission.speakers.first().get_display_name()
                    if item.submission.speakers.exists()
                    else None
                )
            ),
            "description": item.submission.abstract if item.submission else None,
            "category":  str(item.submission.track.name) if item.submission and item.submission.track else None,
            "start": item.local_start.isoformat() if item.local_start else None,
            "end": item.local_end.isoformat() if item.local_end else None,
            "duration": item.export_duration if item.local_start else None,
            "venue": str(item.room.name) if item.room else None,
            "colour": item.submission.track.color if item.submission and item.submission.track else None,
        }
        json_str = json.dumps(talk_details, cls=DjangoJSONEncoder)
        json_str = json_str.replace(" ", "%20")
        return json_str

    def item_link(self, item: Any):
        return "https://wsaf.org.uk"  # No link, but required by the feed format
