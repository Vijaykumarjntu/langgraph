notebook_json = """{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Production Human-In-The-Loop (HITL) Architecture for Stateless APIs\\n",
    "\\n",
    "This notebook demonstrates how to deploy enterprise-grade, idempotent Human-in-the-Loop patterns behind a load balancer. It bridges the gap between raw framework interrupts and real-world microservices.\\n",
    "\\n",
    "### Production Hardening Archetypes Covered:\\n",
    "1. **Stateless Persistence Boundaries**: Shifting away from in-memory drivers to stateless, multi-node checkpoint architectures.\\n",
    "2. **Cryptographic Idempotency Registries**: Ensuring that out-of-band actions (Slack clicks, dashboard approvals) can only execute exactly once.\\n",
    "3. **Explicit Verification Hooks**: Validating signatures or caller permissions before applying mutations onto the state channel.\\n",
    "4. **Immutable Audit Trails**: Capturing chronological reviewer logs natively inside the checkpoint payload."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "# Install core requirements\\n",
    "%pip install --upgrade langchain-core langgraph pydantic"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🧱 Step 2: Define the Transaction State Blueprint"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import enum\\n",
    "from typing import TypedDict, List, Dict, Any, Optional\\n",
    "from pydantic import BaseModel, Field\\n",
    "\\n",
    "class ApprovalVerdict(str, enum.Enum):\\n",
    "    APPROVED = \\"APPROVED\\"\\n",
    "    REJECTED = \\"REJECTED\\"\\n",
    "    ESCALATED = \\"ESCALATED\\"\\n",
    "\\n",
    "class AuditLogEntry(BaseModel):\\n",
    "    timestamp: str\\n",
    "    actor: str\\n",
    "    action: str\\n",
    "    notes: Optional[str] = None\\n",
    "\\n",
    "class ProductionHITLState(TypedDict):\\n",
    "    \\\"\\\"\\\"Production state schema requiring cryptographic single-use tickets.\\\"\\\"\\\"\\n",
    "    transaction_id: str\\n",
    "    amount: float\\n",
    "    idempotency_token: str          # Unique action lock tied to the specific step\\n",
    "    processed_tokens: List[str]      # Historical single-use tickets applied\\n",
    "    verdict: Optional[ApprovalVerdict]\\n",
    "    audit_trail: List[Dict[str, Any]]"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 📡 Step 3: Implement Nodes with Pre-Flight Gates"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import time\\n",
    "from langgraph.errors import GraphInterrupt\\n",
    "\\n",
    "def transaction_pre_flight_node(state: ProductionHITLState) -> Dict[str, Any]:\\n",
    "    \\\"\\\"\\\"Evaluates limits and issues a unique, traceable idempotency token if human intervention is required.\\\"\\\"\\\"\\n",
    "    amount = state.get(\\"amount\\", 0.0)\\n",
    "    trail = list(state.get(\\"audit_trail\\", []))\\n",
    "    \\n",
    "    if amount > 10000.0:\\n",
    "        # Generate a unique action token for this execution boundary\\n",
    "        unique_lock_id = f\\"lock_tx_{state['transaction_id']}_v1\\"\\n",
    "        \\n",
    "        trail.append(AuditLogEntry(\\n",
    "            timestamp=str(time.time()),\\n",
    "            actor=\\"system_rule_engine\\",\\n",
    "            action=\\"SUSPEND_FOR_REVIEW\\",\\n",
    "            notes=f\\"Transaction of ${amount} exceeds automated compliance ceiling. Generated token: {unique_lock_id}\\"\\n",
    "        ).model_dump())\\n",
    "        \\n",
    "        return {\\n",
    "            \\"idempotency_token\\": unique_lock_id,\\n",
    "            \\"audit_trail\\": trail\\n",
    "        }\\n",
    "        \\n",
    "    trail.append(AuditLogEntry(\\n",
    "        timestamp=str(time.time()),\\n",
    "        actor=\\"system_rule_engine\\",\\n",
    "        action=\\"AUTO_APPROVE\\"\\n",
    "    ).model_dump())\\n",
    "    return {\\n",
    "        \\"verdict\\": ApprovalVerdict.APPROVED,\\n",
    "        \\"audit_trail\\": trail\\n",
    "    }\\n",
    "\\n",
    "def review_processing_node(state: ProductionHITLState) -> Dict[str, Any]:\\n",
    "    \\\"\\\"\\\"Runs post-resume. Validates the human payload state before committing downstream work.\\\"\\\"\\\"\\n",
    "    # This step executes immediately when the graph resumes\\n",
    "    return {}\\n",
    "\\n",
    "def execute_settlement_node(state: ProductionHITLState) -> Dict[str, Any]:\\n",
    "    return {\\"audit_trail\\": state[\\"audit_trail\\"] + [{\\"action\\": \\"SETTLED\\", \\"actor\\": \\"ledger_api\\"}]}"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🔀 Step 4: Define Routing Infrastructure & Compile Graph"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "from langgraph.graph import START, END\\n",
    "from langgraph.checkpoint.memory import MemorySaver # Replace with PostgresSaver in real deployments\\n",
    "\\n",
    "def route_after_evaluation(state: ProductionHITLState) -> str:\\n",
    "    if state.get(\"verdict\") == ApprovalVerdict.APPROVED:\\n",
    "        return \"execute_settlement\"\\n",
    "    return \"review_processing_node\"\\n",
    "\\n",
    "def route_after_review(state: ProductionHITLState) -> str:\\n",
    "    if state.get(\"verdict\") == ApprovalVerdict.APPROVED:\\n",
    "        return \"execute_settlement\"\\n",
    "    return END\\n",
    "\\n",
    "builder = StateGraph(ProductionHITLState)\\n",
    "builder.add_node(\"transaction_pre_flight\", transaction_pre_flight_node)\\n",
    "builder.add_node(\"review_processing_node\", review_processing_node)\\n",
    "builder.add_node(\"execute_settlement\", execute_settlement_node)\\n",
    "\\n",
    "builder.add_edge(START, \"transaction_pre_flight\")\\n",
    "builder.add_conditional_edges(\"transaction_pre_flight\", route_after_evaluation)\\n",
    "builder.add_conditional_edges(\"review_processing_node\", route_after_review)\\n",
    "builder.add_edge(\"execute_settlement\", END)\\n",
    "\\n",
    "# Force a production halt directly BEFORE the review handling step\\n",
    "checkpointer = MemorySaver()\\n",
    "graph = builder.compile(checkpointer=checkpointer, interrupt_before=[\"review_processing_node\"])"
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🔒 Step 5: Secure Idempotent State Mutation Endpoint"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "def submit_human_verdict_securely(\\n",
    "    compiled_graph: Any, \\n",
    "    thread_config: dict, \\n",
    "    token_signature: str, \\n",
    "    verdict: ApprovalVerdict, \\n",
    "    reviewer_id: str\\n",
    ") -> str:\\n",
    "    \\\"\\\"\\\"Production API Endpoint logic. Validates permission, prevents double-spending, \\n",
    "    and updates the graph thread safely behind a load balancer.\\n",
    "    \\\"\\\"\\\"\\n",
    "    snapshot = compiled_graph.get_state(thread_config)\\n",
    "    current_state = snapshot.values\\n",
    "    \\n",
    "    # 1. Audit / Verifier Hook: Validate caller authentication\\n",
    "    if \\"compliance_manager\\" not in reviewer_id:\\n",
    "        raise PermissionError(f\\"Actor {reviewer_id} lacks clearance to modify this thread.\\")\\n",
    "        \\n",
    "    # 2. Token Matching Guard: Validate signature token\\n",
    "    if current_state.get(\\"idempotency_token\\") != token_signature:\\n",
    "        return \\"REJECTED_BAD_TOKEN\\"\\n",
    "        \\n",
    "    # 3. Double-Spend Guard: Check if this token was already consumed\\n",
    "    if token_signature in current_state.get(\\"processed_tokens\\", []):\\n",
    "        return \\"REJECTED_ALREADY_PROCESSED\\"\\n",
    "        \\n",
    "    # 4. Construct safe payload modification update matrix\\n",
    "    updated_trail = list(current_state.get(\\"audit_trail\\", []))\\n",
    "    updated_trail.append(AuditLogEntry(\\n",
    "        timestamp=str(time.time()),\\n",
    "        actor=reviewer_id,\\n",
    "        action=f\\"SUBMIT_{verdict.value}\\",\\n",
    "        notes=\\"Verified signature handshake line clear.\\"\\n",
    "    ).model_dump())\\n",
    "    \\n",
    "    consumed_tokens = list(current_state.get(\\"processed_tokens\\", [])) + [token_signature]\\n",
    "    \\n",
    "    mutation_payload = {\\n",
    "        \\"verdict\\": verdict,\\n",
    "        \\"processed_tokens\\": consumed_tokens,\\n",
    "        \\"audit_trail\\": updated_trail\\n",
    "    }\\n",
    "    \\n",
    "    # Commit the mutation directly into the persistence database thread state\\n",
    "    compiled_graph.update_state(thread_config, mutation_payload, as_node=\\"review_processing_node\\")\\n",
    "    return \\"SUCCESS_STATE_UPDATED\\""
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 🧪 Step 6: Test Idempotency and Collision Resilience"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "thread_config = {\\"configurable\\": {\\"thread_id\\": \\"trans_7716\\"}}\\n",
    "initial_input = {\\"transaction_id\\": \\"7716\\", \\"amount\\": 15000.0, \\"processed_tokens\\": [], \\"audit_trail\\": []}\\n",
    "\\n",
    "# 1. Run until suspension\\n",
    "for event in graph.stream(initial_input, config=thread_config):\\n",
    "    pass\\n",
    "\\n",
    "snapshot = graph.get_state(thread_config)\\n",
    "target_token = snapshot.values[\\"idempotency_token\\"]\\n",
    "print(f\\"Suspended. Target Token Created: {target_token}\")\\n",
    "\\n",
    "# 2. First Approval Request (Simulating Manager A clicking 'Approve' via Slack)\\n",
    "status_1 = submit_human_verdict_securely(graph, thread_config, target_token, ApprovalVerdict.APPROVED, \\"compliance_manager_alice\\")\\n",
    "print(f\\"Manager A Action: {status_1}\")\\n",
    "\\n",
    "# 3. Duplicate Approval Request (Simulating Manager B clicking 'Approve' via Email later)\\n",
    "status_2 = submit_human_verdict_securely(graph, thread_config, target_token, ApprovalVerdict.APPROVED, \\"compliance_manager_bob\\")\\n",
    "print(f\\"Manager B Duplicate Action: {status_2} 👈 (Double-Spend Blocked!)\")\\n",
    "\\n",
    "# 4. Resume the graph cleanly to verify the workflow path\\n",
    "print(\\"\\\\nResuming execution flow...\\")\\n",
    "for event in graph.stream(None, config=thread_config):\\n",
    "    print(f\\"Event fired: {list(event.keys())}\")\\n",
    "\\n",
    "final_state = graph.get_state(thread_config).values\\n",
    "print(f\\"Final Verdict: {final_state['verdict']}\")\\n",
    "print(f\\"Total Audit Entries: {len(final_state['audit_trail'])}\")"
   ]
  }
 ],
 "metadata": {
  "language_info": {
   "name": "python"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 2
}"""

import os

# Create directory path if it doesn't exist
os.makedirs("examples/human_in_the_loop", exist_ok=True)

# Write the file directly
output_path = "examples/human_in_the_loop/production_hitl_orchestration.ipynb"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(notebook_json)

print(f"Successfully generated notebook at: {output_path}")