from pytest_mock_resources import create_redis_fixture

redis = create_redis_fixture()


def test_pytest_mock_redis(redis):
    colorSet = "Colors"
    redis.sadd(colorSet, "Red")
    redis.sadd(colorSet, "Orange")
    redis.sadd(colorSet, "Yellow")
    redis.sadd(colorSet, "Green")
    redis.sadd(colorSet, "Blue")
    redis.sadd(colorSet, "Indigo")
    redis.sadd(colorSet, "violet")

    print("Cardinality of the Redis set:")
    print(redis.scard(colorSet))
    print("Contents of the Redis set:")
    print(redis.smembers(colorSet))

def test_publishing_of_notifications_to_a_cache_buffer_temporary_store_queue(redis):
    pass

def test_acknowledgement_pulse_or_retrieval_of_cached_buffered_notifications(redis):
    pass

def test_polling_or_retrieval_of_cached_buffered_notifications_in_a_batch_list(redis):
    pass

def test_bulk_save_of_cached_buffered_notifications_in_a_batch_list(redis):
    pass