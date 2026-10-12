package release_gate

import rego.v1

test_generated_requests if {
    count(data.cases) > 0
    every test in data.cases {
        expected := test.expected == "allow"
        actual := allow with input as test.request
        actual == expected
    }
}
