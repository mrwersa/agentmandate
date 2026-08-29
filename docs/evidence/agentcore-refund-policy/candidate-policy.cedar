permit(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"RefundIamTarget___process_refund",
  resource == AgentCore::Gateway::"<reviewed-gateway-binding>"
)
when {
  context.input.amount < 3000
};
