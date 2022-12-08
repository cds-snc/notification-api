
def pytest_addoption(parser):
    parser.addoption("--environment", action="store", default="some env")


def pytest_generate_tests(metafunc):
    # This is called for every test. Only get/set command line arguments
    # if the argument is specified in the list of test "fixturenames".
    option_value = metafunc.config.option.environment
    if 'environment' in metafunc.fixturenames and option_value is not None:
        metafunc.parametrize("environment", [option_value],  scope="session")


def pytest_runtest_logreport(report):
    sensitive_words = ["key", "token"]
    
    if report.longrepr is None:
        return
    for tb_repr, *_ in report.longrepr.chain:
        for entry in tb_repr.reprentries:
            if entry.reprfuncargs is not None:
                args = entry.reprfuncargs.args
                for idx, (name, value) in enumerate(args):
                    for keyword in sensitive_words:
                        if keyword in name:
                            args[idx] = (name, "********")
            if entry.reprlocals is not None:
                lines = entry.reprlocals.lines
                for idx, line in enumerate(lines):
                    for keyword in sensitive_words:
                        if keyword in line:
                            lines[idx] = "sensitive          = '*********'"
