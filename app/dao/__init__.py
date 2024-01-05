from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from app import db


# Should I use SQLAlchemyError?
class DAOException(SQLAlchemyError):
    pass


class DAOClass(object):

    class Meta:
        model = None

    def create_instance(self, inst, _commit=True):
        db.session.add(inst)
        if _commit:
            db.session.commit()

    def update_instance(self, inst, update_dict, _commit=True):
        # Make sure the id is not included in the update_dict
        update_dict.pop('id')
        stmt = update(self.Meta.model).where(self.Meta.model.id == inst.id).values(**update_dict)
        db.session.execute(stmt)
        if _commit:
            db.session.commit()

    def delete_instance(self, inst, _commit=True):
        db.session.delete(inst)
        if _commit:
            db.session.commit()
