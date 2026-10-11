package release_gate

import rego.v1

default allow := false

allow if {
    is_object(input)
    is_string(input.principal)
    is_string(input.action)
    is_string(input.resource)
    is_object(input.context)
    input.principal in {"release-operator"}
    input.action == "PublishRelease"
    input.resource == "release-tools"
    input.context["approved"] == true
}

allow if {
    is_object(input)
    is_string(input.principal)
    is_string(input.action)
    is_string(input.resource)
    is_object(input.context)
    input.principal in {"build-reader"}
    input.action == "ReadBuildStatus"
    input.resource == "release-tools"
}

allow if {
    is_object(input)
    is_string(input.principal)
    is_string(input.action)
    is_string(input.resource)
    is_object(input.context)
    input.principal in {"release-operator"}
    input.action == "ReadRelease"
    input.resource == "release-tools"
}
