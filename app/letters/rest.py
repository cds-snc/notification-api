from flask import Blueprint, jsonify, request

from app.letters.letter_schemas import letter_references
from app.schema_validation import validate
from app.v2.errors import register_errors

letter_job = Blueprint("letter-job", __name__)
register_errors(letter_job)


@letter_job.route("/letters/returned", methods=["POST"])
def create_process_returned_letters_job():
    references = validate(request.get_json(), letter_references)

    return jsonify(references=references["references"]), 200
