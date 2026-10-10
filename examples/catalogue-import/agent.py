"""Synthetic dynamic binding. This file is read statically, never executed."""

from example_framework import Agent, provider

resolver = Agent(tools=provider.for_tenant("example"))
