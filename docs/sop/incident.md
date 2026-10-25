# Incident response

1. A P1 arrives (Azure Monitor push or SMS, or an iMessage from the Mac Mini heartbeat).
2. Open the admin UI Fleet home, or ask Claude: "summarize open incidents and what changed in the last 24 hours".
3. Contain from the UI. Every action is audited:
   - Bad release: Deployments, Roll back (prod needs approval with MFA).
   - Suspicious traffic: turn on origin restriction for the app (approval required) to allow only the client's VPN.
   - Leaked secret: Secrets, Rotate.
4. If the Mac Mini says the platform worker is stale but apps are up, the control plane is degraded, not the apps:
   check `ca-platform-api-prod` and the `caj-platform-*` job executions in the Azure portal.
5. Close the incident in Sentinel with a one-line cause and fix. It shows in the next digest.
