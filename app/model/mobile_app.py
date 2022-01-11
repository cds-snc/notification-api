from app.db import db


class MobileApp(db.Model):
    __tablename__ = "mobile_app"

    app_sid = db.Column(db.String(100), primary_key=True)
    app_name = db.Column(db.Sting(100), primary_key=True)

    @classmethod
    def find_by_app_name(cls, app_name: str) -> "MobileApp":
        return cls.query.filter_by(app_name=app_name).first()

    @classmethod
    def find_by_app_sid(cls, app_sid: str) -> "MobileApp":
        return cls.query.filter_by(app_sid=app_sid).first()

    @classmethod
    def delete_by_id(cls, app_sid: str) -> "MobileApp":
        cls.query.filter_by(app_sid=app_sid).first()

    def save_to_db(self) -> None:
        db.session.add(self)
        db.session.commit()

    def delete_from_db(self) -> None:
        db.session.delete(self)
        db.session.commit()
