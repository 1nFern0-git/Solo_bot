from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, String

from ._base import Base, DictLikeMixin


class Key(DictLikeMixin, Base):
    __tablename__ = "keys"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, nullable=False, index=True)
    client_id = Column(String, primary_key=True)
    tg_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=True, index=True)
    email = Column(String, unique=True)
    created_at = Column(BigInteger)
    expiry_time = Column(BigInteger)
    key = Column(String)
    server_id = Column(String)
    remnawave_link = Column(String)
    tariff_id = Column(Integer, ForeignKey("tariffs.id", ondelete="SET NULL"))
    is_frozen = Column(Boolean, default=False)
    alias = Column(String)
    notified = Column(Boolean, default=False)
    notified_24h = Column(Boolean, default=False)

    selected_device_limit = Column(Integer, nullable=True)
    selected_traffic_limit = Column(BigInteger, nullable=True)
    selected_price_rub = Column(Integer, nullable=True)

    current_device_limit = Column(Integer, nullable=True)
    current_traffic_limit = Column(BigInteger, nullable=True)
