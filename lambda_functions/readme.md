# Lambdas and Layers

| Lambda Name | Layers Used |
| ---- | ---- |
| bip_kafka_consumer_lambda | kafka-consumer |
| bip_msg_mpi_lookup_lambda | aiohttp |
| delivery_status_processor_lambda | twilio |
| nightly_billing_stats_upload_lambda | bigquery |
| nightly_stats_bigquery_upload_lambda | bigquery |
| pinpoint_callback_lambda |  |
| pinpoint_inbound_sms_lambda |  |
| ses_callback_lambda |  |
| two_way_sms_lambda |  |
| two_way_sms_v2 | psycopg2-binary, requests |
| va_profile_opt_in_out_lambda | psycopg2-binary, pyjwt |
| va_profile_remove_old_opt_outs_lambda | psycopg2-binary |
| vetext_incoming_forwarder_lambda | twilio |

**Note:** _PyJWT Layer_  
Whenever PyJWT[crypto] (pyjwt-layer) is updated, we also must ensure compatability with Poetry. That is done by ensuring the same version of PyJWT exists in the `poetry.lock` file. The `poetry.lock` file must never be manually changed. Make any changes to `pyproject.toml`, run the `poetry update` command,  and ensure they appear as desired in the `poetry.lock` file.

**Note:** _Python Version and urllib3_  
Our lambdas currently use python3.8 and we can't use anything newer than 3.9 without updating our AWS provider version
in our infrastructure code. This also means that any lambda layer importing urllib3 will need to pin urllib3 to version 
<2 until we can get things updated to the point of using python3.10 or newer.
