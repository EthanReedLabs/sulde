--------------------------- MODULE DenialRecovery ---------------------------
EXTENDS Naturals
CONSTANT FalsePauseBug
VARIABLES phase, paused, highRiskAllowed, highRiskExecuted, outcome, oldDebt
vars == <<phase, paused, highRiskAllowed, highRiskExecuted, outcome, oldDebt>>
Init == /\ phase = "shape_pending" /\ paused = FALSE
        /\ highRiskAllowed = FALSE /\ highRiskExecuted = FALSE
        /\ outcome = "unobserved" /\ oldDebt = "unknown"
DenyShape == /\ phase = "shape_pending"
             /\ phase' = "shape_denied" /\ paused' = FalsePauseBug
             /\ UNCHANGED <<highRiskAllowed, highRiskExecuted, outcome, oldDebt>>
NextOrdinary == /\ phase = "shape_denied" /\ ~paused
                /\ phase' = "ordinary_running" /\ outcome' = "unknown"
                /\ UNCHANGED <<paused, highRiskAllowed, highRiskExecuted, oldDebt>>
IndependentVerify == /\ phase = "ordinary_running"
                     /\ phase' = "ordinary_verified" /\ outcome' = "verified"
                     /\ UNCHANGED <<paused, highRiskAllowed, highRiskExecuted, oldDebt>>
DenyHighRisk == /\ phase = "ordinary_verified"
                /\ phase' = "risk_denied" /\ paused' = TRUE
                /\ UNCHANGED <<highRiskAllowed, highRiskExecuted, outcome, oldDebt>>
NativeAllow == /\ phase = "risk_denied"
               /\ phase' = "risk_authorized" /\ highRiskAllowed' = TRUE
               /\ paused' = FALSE
               /\ UNCHANGED <<highRiskExecuted, outcome, oldDebt>>
ExecuteHighRisk == /\ phase = "risk_authorized" /\ highRiskAllowed /\ ~paused
                   /\ phase' = "risk_executed" /\ highRiskExecuted' = TRUE
                   /\ outcome' = "unknown"
                   /\ UNCHANGED <<paused, highRiskAllowed, oldDebt>>
Next == DenyShape \/ NextOrdinary \/ IndependentVerify \/ DenyHighRisk
        \/ NativeAllow \/ ExecuteHighRisk
Spec == Init /\ [][Next]_vars /\ WF_vars(DenyShape)
        /\ WF_vars(NextOrdinary) /\ WF_vars(IndependentVerify)
NoFalsePause == phase = "shape_denied" => ~paused
NoUnapprovedExecution == highRiskExecuted => highRiskAllowed
NoDebtForgery == oldDebt = "unknown"
NoPreDenialEffect == phase \in {"shape_pending", "shape_denied"} => outcome = "unobserved"
OrdinaryProgress == phase = "shape_denied" ~> phase = "ordinary_verified"
=============================================================================
