from dataclasses import dataclass, field


@dataclass
class User:
    id: str
    email: str
    name: str
    password_hash: str = ""
    roles: list = field(default_factory=lambda: ["customer"])

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles
