import pytest

from app.errors import (
    CannotSaveDuplicateEmailBrandingError,
    CannotSaveDuplicateTemplateCategoryError,
    DuplicateEntityError,
)


class CannotSaveDuplicateEntityFourFieldsError(DuplicateEntityError):
    entity = "test_entity"
    fields = ["more", "than", "three", "fields"]

    def __init__(self, status_code=400):
        super().__init__(fields=self.fields, entity=self.entity, status_code=status_code)


def test_duplicate_entity_error_formats_messages_correctly():
    with pytest.raises(CannotSaveDuplicateEmailBrandingError) as e:
        raise CannotSaveDuplicateEmailBrandingError()

    assert e.value.message == "Email branding already exists, name must be unique."
    assert e.value.status_code == 400

    with pytest.raises(CannotSaveDuplicateTemplateCategoryError) as e:
        raise CannotSaveDuplicateTemplateCategoryError()

    assert e.value.message == "Template category already exists, name_en and name_fr must be unique."
    assert e.value.status_code == 400

    with pytest.raises(CannotSaveDuplicateEntityFourFieldsError) as e:
        raise CannotSaveDuplicateEntityFourFieldsError()

    assert e.value.message == "test_entity already exists, more, than, three and fields must be unique."
    assert e.value.status_code == 400

    with pytest.raises(DuplicateEntityError) as e:
        raise DuplicateEntityError()

    assert e.value.message == "Entity already exists."
    assert e.value.status_code == 400
