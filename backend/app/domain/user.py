"""Доменная сущность пользователя."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .exceptions import InvalidEmailError


# TODO: Реализовать класс User
# - Использовать @dataclass
# - Поля: email, name, id, created_at
# - Реализовать валидацию email в __post_init__
# - Regex: r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

@dataclass
class User:
    email: str
    name: str = ""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.email or not self.email.strip():
            raise InvalidEmailError(self.email)
        if not re.match(EMAIL_REGEX, self.email):
            raise InvalidEmailError(self.email)