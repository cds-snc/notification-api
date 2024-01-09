from sqlalchemy.dialects.postgresql import UUID
from app.db import db


class IdentityProviderIdentifier(db.Model):
    __tablename__ = 'users_idp_ids'
    __table_args__ = (db.Index('ix_users_idp_ids_idp_name_idp_id', 'idp_name', 'idp_id', unique=True),)

    user_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey('users.id', ondelete='cascade'), primary_key=True, nullable=False
    )
    idp_name = db.Column(db.String, primary_key=True, nullable=False)
    idp_id = db.Column(db.String, nullable=False)

    def __init__(
        self,
        user_id,
        idp_name,
        idp_id,
    ):
        self.user_id = user_id
        self.idp_name = idp_name
        self.idp_id = idp_id
