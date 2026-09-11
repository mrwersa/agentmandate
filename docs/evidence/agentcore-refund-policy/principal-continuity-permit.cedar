permit (
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"PrincipalTarget___process_refund",
  resource == AgentCore::Gateway::"<reviewed-principal-continuity-gateway>"
);
