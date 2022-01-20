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
