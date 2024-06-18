# Smoke Tests

This repository contains a set of smoke tests for our application. Smoke testing, also known as "Build Verification Testing", is a type of software testing that comprises of a non-exhaustive set of tests that aim at ensuring that the most important functions work. The phrase 'smoke testing' comes from the hardware testing, where you plug in a new piece of hardware and turn it on for the first time. If it starts smoking, you know you have a problem.

## Getting Started

These smoke tests are designed to run in the api devcontainer.

in the root of the repo create `.env` files for the environments you with to smoke test, for example `.env_smoke_local`, `.env_smoke_staging`, and `.env_smoke_prod`. For required values see the [.env.example](.env.example) file).

## Running the tests

in the devcontainer run the aliases `smoke-local`, `smoke-staging`, or `smoke-prod` to run the tests.

