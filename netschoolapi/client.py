from datetime import date, timedelta
from hashlib import md5
from typing import List, Optional, Tuple

from httpx import AsyncClient

from netschoolapi import data, exceptions
from netschoolapi.login_form import _get_login_form
from netschoolapi.utils import _json_or_panic


class NetSchoolAPI:
    def __init__(
        self,
        url: str,
        user_name: str,
        password: str,
        school: Tuple[str, str, str, str, str],
    ) -> None:
        self._client = AsyncClient(
            base_url=f'{url.rstrip("/")}/webapi',
            headers={"user-agent": "NetSchoolAPI/4.0.2", "referer": url},
        )
        self._user_name = user_name
        self._password = password

        self._school = school

        self._user_id = None
        self._year_id = None

    async def get_diary(
        self,
        week_start: Optional[date] = None,
        week_end: Optional[date] = None
    ) -> data.Diary:
        if not week_start:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
        if not week_end:
            week_end = week_start + timedelta(days=5)

        async with self._client as client:
            dairy = _json_or_panic(await client.get(
                "student/diary",
                params={
                    "studentId": self._user_id,
                    "weekStart": week_start.isoformat(),
                    "weekEnd": week_end.isoformat(),
                    "yearId": self._year_id,
                },
            ))
            return data.Diary.from_dict(dairy)

    async def get_announcements(
        self, take: Optional[int] = -1,
    ) -> List[data.Announcement]:
        async with self._client as client:
            announcements = _json_or_panic(await client.get(
                "announcements", params={"take": take},
            ))
            return [data.Announcement.from_dict(a) for a in announcements]

    async def get_details(
        self, assignment: data.Assignment,
    ) -> data.DetailedAssignment:
        async with self._client as client:
            details = _json_or_panic(await client.get(
                f"student/diary/assigns/{assignment.id}"
            ))
            return data.DetailedAssignment.from_dict(details)

    async def get_attachments(
        self, assignments: List[data.Assignment],
    ) -> List[data.Attachment]:
        async with self._client as client:
            attachments = _json_or_panic(await client.post(
                "student/diary/get-attachments",
                params={"studentId": self._user_id},
                json={"assignId": [a.id for a in assignments]},
            ))
            return [data.Attachment.from_dict(a) for a in attachments]

    async def _login(self) -> None:
        async with self._client as client:
            client.cookies.extract_cookies((await client.get("logindata")))

            login_data = _json_or_panic(await client.post("auth/getdata"))
            salt = login_data.pop("salt")

            encoded_password = md5(self._password.encode("windows-1251")).hexdigest().encode()
            pw2 = md5(salt.encode() + encoded_password).hexdigest()
            pw = pw2[: len(self._password)]

            response = _json_or_panic(await client.post(
                "login",
                data={
                    "logintype": 1,
                    **(await _get_login_form(client, self._school)),
                    "un": self._user_name,
                    "pw": pw,
                    "pw2": pw2,
                    **login_data,
                },
            ))

            # at — access token
            if "at" not in response:
                error_message = response["message"]
                if len(error_message) == 29:
                    raise exceptions.LoginDataError
                else:
                    raise exceptions.NetSchoolAPIError(error_message)

            client.headers["at"] = response["at"]

            diary = _json_or_panic(await client.get("student/diary/init"))
            student = diary["students"][diary["currentStudentId"]]
            self._user_id = student["studentId"]

            context = _json_or_panic(await client.get("context"))
            self._year_id = context["schoolYearId"]

    async def _logout(self) -> None:
        async with self._client as client:
            await client.post("auth/logout")

    async def __aenter__(self) -> "NetSchoolAPI":
        await self._login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._logout()
