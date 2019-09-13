workflow "Publish to SNS topic" {
  on = "push"
  resolves = ["Topic"]
}

action "Topic" {
  uses = "actions/docker/cli@master"
  args = "build -t user/repo ."
}