# terraform.tfvars, which setup writes, sets these.

variable "name" {
  description = "The project's name: realm.toml's [realm] name."
  type        = string
}

variable "region" {
  description = "The AWS region: realm.toml's [deploy] region."
  type        = string
}
