permit(principal, action == ReleaseGate::Action::"PublishRelease", resource == ReleaseGate::Repository::"release-tools")
when { (principal == ReleaseGate::User::"release-operator") && context has approved && context.approved };

permit(principal, action == ReleaseGate::Action::"ReadBuildStatus", resource == ReleaseGate::Repository::"release-tools")
when { (principal == ReleaseGate::Workload::"build-reader") };

permit(principal, action == ReleaseGate::Action::"ReadRelease", resource == ReleaseGate::Repository::"release-tools")
when { (principal == ReleaseGate::User::"release-operator") };
