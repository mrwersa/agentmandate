permit (
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"ContinuationTarget___process_refund",
  resource == AgentCore::Gateway::"<reviewed-continuation-gateway>"
);
