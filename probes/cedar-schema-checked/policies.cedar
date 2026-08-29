permit(principal, action == Action::"Read", resource);
forbid(principal, action == Action::"Read", resource) when { resource.blocked };
