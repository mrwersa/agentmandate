permit (
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"RetryTarget___process_refund",
  resource == AgentCore::Gateway::"<reviewed-retry-continuity-gateway>"
);
