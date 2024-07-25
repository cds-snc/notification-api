from flask import Blueprint

from app.v2.errors import register_errors

letter_job = Blueprint("letter-job", __name__)
register_errors(letter_job)


@letter_job.route("/letters/returned", methods=["POST"])
def create_process_returned_letters_job():
    pass
