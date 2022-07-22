from locust import events


@events.init_command_line_parser.add_listener
def init_parser(parser):
    parser.add_argument("--ref", type=str, default="perf test", help="reference string for database search")
