import datetime as dt

from django.http import JsonResponse
from django.utils.functional import cached_property
from django.views import View
from i18nfield.utils import I18nJSONEncoder
from pretalx import __version__
from pretalx.agenda.views.schedule import ScheduleMixin
from pretalx.common.exporter import BaseExporter
from pretalx.common.urls import get_base_url
from pretalx.submission.models import SubmissionStates


class WSAFScheduleData(BaseExporter):
    """Export schedule with displayed work as a separate day."""

    def __init__(self, event, schedule=None, with_accepted=False, with_breaks=False):
        super().__init__(event)
        self.schedule = schedule
        self.with_accepted = with_accepted
        self.with_breaks = with_breaks

    @cached_property
    def metadata(self):
        if not self.schedule:
            return []

        return {
            "url": self.event.urls.schedule.full(),
            "base_url": get_base_url(self.event),
        }

    @cached_property
    def data(self):
        if not self.schedule:
            return []

        event = self.event
        schedule = self.schedule

        base_qs = (
            schedule.talks.all()
            if self.with_accepted
            else schedule.talks.filter(is_visible=True)
        )
        talks = (
            base_qs.select_related(
                "submission",
                "submission__event",
                "submission__submission_type",
                "submission__track",
                "room",
            )
            .prefetch_related("submission__speakers")
            .order_by("start")
            .exclude(submission__state="deleted")
        )
        data = {
            current_date.date(): {
                "index": index + 1,
                "start": current_date.replace(hour=4, minute=0).astimezone(event.tz),
                "end": current_date.replace(hour=3, minute=59).astimezone(event.tz)
                + dt.timedelta(days=1),
                "first_start": None,
                "last_end": None,
                "rooms": {},
            }
            for index, current_date in enumerate(
                event.datetime_from + dt.timedelta(days=days)
                for days in range((event.date_to - event.date_from).days + 1)
            )
        }

        gallery_room = event.rooms.filter(name__icontains="gallery").first()
        print(f"Using gallery room: {gallery_room}")
        data["gallery"] = {
            "index": "gallery",
            "start": event.datetime_from.replace(hour=9, minute=0).astimezone(event.tz),
            "end": event.datetime_to.replace(hour=22, minute=00).astimezone(event.tz),
            "rooms": {
                str(gallery_room.name): {
                    "id": gallery_room.id,
                    "guid": gallery_room.uuid,
                    "name": gallery_room.name,
                    "description": gallery_room.description,
                    "position": gallery_room.position,
                    "talks": [],
                }
            },
        }

        if self.with_accepted:
            allowed_states = [
                SubmissionStates.ACCEPTED,
                SubmissionStates.CONFIRMED,
            ]
        else:
            allowed_states = [
                SubmissionStates.CONFIRMED,
            ]

        gallery_talks = (
            schedule.talks.filter(
                is_visible=False,
                start__isnull=True,
            )
            .select_related(
                "submission",
                "submission__event",
                "submission__submission_type",
                "submission__track",
                "room",
            )
            .prefetch_related("submission__speakers")
            .exclude(submission__state="deleted")
            .filter(
                submission__isnull=False,
                submission__track__name__icontains="displayed",
                submission__state__in=allowed_states,
            )
        )

        for talk in gallery_talks:
            data["gallery"]["rooms"][str(gallery_room.name)]["talks"].append(talk)

        for talk in talks:
            if (
                not talk.start
                or not talk.room
                or (not talk.submission and not self.with_breaks)
            ):
                continue

            talk_date = talk.local_start.date()
            if talk.local_start.hour < 3 and talk_date != event.date_from:
                talk_date -= dt.timedelta(days=1)
            day_data = data.get(talk_date)
            if not day_data:
                continue
            if str(talk.room.name) not in day_data["rooms"]:
                day_data["rooms"][str(talk.room.name)] = {
                    "id": talk.room.id,
                    "guid": talk.room.uuid,
                    "name": talk.room.name,
                    "description": talk.room.description,
                    "position": talk.room.position,
                    "talks": [talk],
                }
            else:
                day_data["rooms"][str(talk.room.name)]["talks"].append(talk)
            if not day_data["first_start"] or talk.start < day_data["first_start"]:
                day_data["first_start"] = talk.start
            if not day_data["last_end"] or talk.local_end > day_data["last_end"]:
                day_data["last_end"] = talk.local_end

        for day in data.values():
            day["rooms"] = sorted(
                day["rooms"].values(),
                key=lambda room: (
                    room["position"] if room["position"] is not None else room["id"]
                ),
            )

        return data.values()


class WSAFJsonView(View, ScheduleMixin):
    identifier = "schedule.json"
    verbose_name = "JSON (frab compatible)"
    public = True
    icon = "{ }"
    cors = "*"

    def get(self, request, *args, **kwargs):
        self.event = self.request.event
        self.schedule_data = WSAFScheduleData(
            event=self.request.event,
            schedule=self.schedule,
        )

        content = self.get_data()
        return JsonResponse(
            {
                "generator": {"name": "pretalx-wsaf-tools", "version": __version__},
                "schedule": content,
            },
            encoder=I18nJSONEncoder,
        )

    def get_data(self, **kwargs):
        schedule = self.schedule_data
        return {
            "url": schedule.metadata["url"],
            "version": self.version,
            "base_url": schedule.metadata["base_url"],
            "conference": {
                "acronym": schedule.event.slug,
                "title": str(schedule.event.name),
                "start": schedule.event.date_from.strftime("%Y-%m-%d"),
                "end": schedule.event.date_to.strftime("%Y-%m-%d"),
                "daysCount": schedule.event.duration,
                "timeslot_duration": "00:05",
                "time_zone_name": schedule.event.timezone,
                "colors": {"primary": schedule.event.primary_color or "#3aa57c"},
                "rooms": [
                    {
                        "name": str(room.name),
                        "slug": room.slug,
                        # TODO room url
                        "guid": room.uuid,
                        "description": str(room.description) or None,
                        "capacity": room.capacity,
                    }
                    for room in self.event.rooms.all()
                ],
                "tracks": [
                    {
                        "name": str(track.name),
                        "slug": track.slug,
                        "color": track.color,
                    }
                    for track in self.event.tracks.all()
                ],
                "days": [
                    {
                        "index": day["index"],
                        "date": day["start"].strftime("%Y-%m-%d"),
                        "day_start": day["start"].astimezone(self.event.tz).isoformat(),
                        "day_end": day["end"].astimezone(self.event.tz).isoformat(),
                        "rooms": {
                            str(room["name"]): [
                                {
                                    "guid": talk.uuid,
                                    "code": talk.submission.code,
                                    "id": talk.submission.id,
                                    "logo": (
                                        talk.submission.urls.image.full()
                                        if talk.submission.image
                                        else None
                                    ),
                                    "date": talk.local_start.isoformat()
                                    if talk.local_start
                                    else None,
                                    "start": talk.local_start.strftime("%H:%M")
                                    if talk.local_start
                                    else None,
                                    "duration": talk.export_duration
                                    if talk.local_start
                                    else None,
                                    "room": str(room["name"]),
                                    "slug": talk.frab_slug,
                                    "url": talk.submission.urls.public.full(),
                                    "title": talk.submission.title,
                                    "subtitle": "",
                                    "track": (
                                        str(talk.submission.track.name)
                                        if talk.submission.track
                                        else None
                                    ),
                                    "type": str(talk.submission.submission_type.name),
                                    "language": talk.submission.content_locale,
                                    "abstract": talk.submission.abstract,
                                    "description": talk.submission.description,
                                    "recording_license": "",
                                    "do_not_record": talk.submission.do_not_record,
                                    "persons": [
                                        {
                                            "code": person.code,
                                            "name": person.get_display_name(),
                                            "avatar": person.get_avatar_url(self.event)
                                            or None,
                                            "biography": person.event_profile(
                                                self.event
                                            ).biography,
                                            "public_name": person.get_display_name(),  # deprecated
                                            "guid": person.guid,
                                            "url": person.event_profile(
                                                self.event
                                            ).urls.public.full(),
                                        }
                                        for person in talk.submission.speakers.all()
                                    ],
                                    "links": [
                                        {
                                            "title": resource.description,
                                            "url": resource.link,
                                            "type": "related",
                                        }
                                        for resource in talk.submission.resources.all()
                                        if resource.link
                                    ],
                                    "feedback_url": talk.submission.urls.feedback.full(),
                                    "origin_url": talk.submission.urls.public.full(),
                                    "attachments": [
                                        {
                                            "title": resource.description,
                                            "url": resource.resource.url,
                                            "type": "related",
                                        }
                                        for resource in talk.submission.resources.all()
                                        if not resource.link
                                    ],
                                    "answers": (
                                        [
                                            {
                                                "question": answer.question.id,
                                                "answer": answer.answer,
                                                "options": [
                                                    option.answer
                                                    for option in answer.options.all()
                                                ],
                                            }
                                            for answer in talk.submission.answers.filter(question__is_public=True).all()
                                        ]
                                    ),
                                }
                                for talk in room["talks"]
                            ]
                            for room in day["rooms"]
                        },
                    }
                    for day in schedule.data
                ],
            },
        }
