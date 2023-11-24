import os
import subprocess
import time
from argparse import ArgumentParser

from smoke.common import Attachment_type, Config, Notification_type  # type: ignore
from smoke.test_admin_csv import test_admin_csv  # type: ignore
from smoke.test_admin_one_off import test_admin_one_off  # type: ignore
from smoke.test_api_bulk import test_api_bulk  # type: ignore
from smoke.test_api_one_off import test_api_one_off  # type: ignore

runCount = 0
maxRuns = 0


class bcolors:

    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def init():

    global maxRuns

    parser = ArgumentParser()
    parser.add_argument("-m", "--max-runs", dest="maxruns",
                        help="Set the maximum number of runs you want", metavar="MAXRUNS")
    parser.add_argument("-s", "--source-script", dest="source",
                        help="Pass a shell script to source environment variables from", metavar="SOURCE")
    args = parser.parse_args()

    print(bcolors.OKBLUE)

    print("API Smoke test\n")
    for key in ["API_HOST_NAME", "SERVICE_ID", "EMAIL_TEMPLATE_ID", "SMS_TEMPLATE_ID", "EMAIL_TO", "SMS_TO"]:
        print(f"{key:>17}: {Config.__dict__[key]}")
    print("")

    if args.maxruns is not None:
        print(f"Running smoke tests in a loop up to {args.maxruns} times")
        maxRuns = int(args.maxruns)
    else:
        print("Running smoke tests in a loop indefinitely")

    os.chdir('../')

    if args.source is not None:
        print(f"Sourcing environment variables from external shell script {args.source}")
        subprocess.run(["source", args.source], executable='/bin/bash')

    print(bcolors.ENDC)


init()


while True:

    result = None
    seconds = None
    startTime = None
    endTime = None

    runCount += 1
    print(bcolors.OKBLUE)
    print(f"Running smoke test #{str(runCount)}")
    print(bcolors.ENDC)
    startTime = time.time()

    for notification_type in [Notification_type.EMAIL, Notification_type.SMS]:
        test_admin_one_off(notification_type)
        test_admin_csv(notification_type)
        test_api_one_off(notification_type)
        test_api_bulk(notification_type)
    test_api_one_off(Notification_type.EMAIL, Attachment_type.ATTACHED)
    test_api_one_off(Notification_type.EMAIL, Attachment_type.LINK)

    print(subprocess.STDOUT)
    endTime = time.time()
    totalTime = endTime - startTime
    print(bcolors.OKBLUE)
    print(f"Smoke Test {str(runCount)} complete in {totalTime} seconds")
    print(bcolors.ENDC)
    if maxRuns != 0:
        if maxRuns >= runCount:
            print(bcolors.WARNING)
            print("Run limit reached. Stopping")
            print(bcolors.ENDC)
            break
