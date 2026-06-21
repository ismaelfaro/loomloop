from loomloop import MessageBus, Message


def test_topic_fanout_excludes_sender():
    bus = MessageBus()
    bus.subscribe("a", "topic")
    bus.subscribe("b", "topic")
    bus.register("sender")
    n = bus.publish(Message(topic="topic", payload=1, sender="a"))
    assert n == 1  # delivered to b, not back to a
    assert bus.pending("b") == 1
    assert bus.pending("a") == 0


def test_direct_addressing():
    bus = MessageBus()
    bus.register("x")
    bus.register("y")
    bus.publish(Message(topic="t", payload="hi", sender="x", recipient="y"))
    assert bus.pending("y") == 1
    assert bus.pending("x") == 0


def test_direct_to_unknown_is_dropped():
    bus = MessageBus()
    bus.register("x")
    assert bus.publish(Message(topic="t", payload=1, sender="x", recipient="ghost")) == 0


def test_remove_clears_subscriptions():
    bus = MessageBus()
    bus.subscribe("a", "t")
    bus.remove("a")
    assert bus.publish(Message(topic="t", payload=1, sender="z")) == 0
