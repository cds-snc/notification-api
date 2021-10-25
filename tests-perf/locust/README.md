# Stress tests manual

This manual is meant for the Locust stress tests located in the same folder than this README.

## Goals

The following goals are meant with the stress-tests:

* Monitor behavior of a production-like environment under similar stress.
* Preemptively discover technical issues by overloading our staging environment.
* Fix discovered issues in the production-like environment and propagate to production.

Our stress-tests can also act as load-tests that are ran against our build pipeline in a daily manner at minimum:

* Ensure our system can take the expected daily traffic of notifications that we receive.
* Align and certify our SLA/SLO/SLI agreements negotiated with our clients.
* Discover regressions related to performance that new changes can affect on our code base and infrastructure.

## How to configure the stress tests

There is an override system that [Locust implements with configuration parameters](https://docs.locust.io/en/stable/configuration.html). It can read values from the command-line, environment variables or custom configuration file. The order is, as defined by its own documentation:

```doc
~/locust.conf -> ./locust.conf -> (file specified using --conf) -> env vars -> cmd args
```

Latest values read will override previous ones, hence command-line arguments will take precedence over everything.

The current directory has a `locust.conf` file where default configuration values are defined.

Note that the `host` value can also be defined within the `User` classes such as found in the `locust-notifications.py` file. This overridden value from its parent is the default values but will be overridden by the enumerated mechanism above.

You should not have to modify the configuration to run the stress-tests locally.

## How to run the stress tests

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run:

```shell
locust -f .\locust-notifications.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f .\locust-notifications.py --headless --users=5500 --spawn-rate=200 --run-time=10m
```

You can also modify the *locust.config* file to enable the headless mode and define the necessary users, spawn rate and run time.

### Performance Testing on AWS

#### Overview 

In the Notify staging account you will find an AMI image that you can use to spin up EC2 servers in which you can ssh into and
run the performance testing. 

Use the following link to navigate to the [AMI image](https://ca-central-1.console.aws.amazon.com/ec2/v2/home?region=ca-central-1#Images:visibility=owned-by-me;name=locust-testing-image;sort=name).
Following this right click on the image and click launch. You'll want to launch a minimum of a t2 large as locust is cpu intensive.

By default the image is set up to target the [Jimmy Royer - GC Notify test](https://staging.notification.cdssandbox.xyz/services/2317d68b-f3ab-4949-956d-4367b488db4b)
service on staging when you run the locust test. 

#### Running the tests on EC2

For convenience there are three EC2 servers that have already been created in the Notify staging account 
such that you can log in and immediately run the locust tests. Each one of these servers target a different
service, and you can find out which server targets which service by looking at the `TEST_AUTH_HEADER` entry in the .env 
file.

These servers should be in a stopped state when performance tests aren't being run to avoid AWS
charges on resources we're not actively using. 

##### Step 1. Logging into the EC2 servers

You can find the PEM file (performance_testing.pem) to log into each one of the EC2 servers in the Shared-Notify staging folder 
in lastpass. Download this file locally and then change its permissions such that it can only be accessed by the root user

```shell
$ chmod 400 performance_testing.pem
```

You can then ssh into any of the respective servers 

```shell
$ ssh -i performance_testing.pem ubuntu@{SERVER_IP_ADDRESS}
```

##### Step 2. Change into the root user on the server

You'll need to change into the root user on the server. This is because we need to bind to port 80
on the 0.0.0.0 host. 

```shell
$ sudo su
```

##### Step 4. Set the maximum number of files that can be open to 100240

Locust requires a file descriptor limit of over 100000 usually by default ubuntu sets this at 1024. To set 
this use the ulimit command 

```shell
$ ulimit -n 100240
```
##### Step 5. Activate the virtual environment

```shell
$ source venv/bin/activate
```

##### Step 6. Run the locust interface

```shell
$ locust -f tests-perf/locust/locust-notifications.py --web-host 0.0.0.0 --web-port 80
```

You should then be able to see the locust interface if you navigate to the server's IP address 
in your browser

##### Step 7. Shut down the server when you are finished

To avoid incurring charges on resources that are not being used please put the instances into a 
stopped state when you are finished with the performance testing.
