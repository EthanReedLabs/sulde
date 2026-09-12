------------------------- MODULE SessionContinuity -------------------------
EXTENDS Integers, FiniteSets
CONSTANTS Sessions, CopyAuthorityBug
VARIABLES started, indexed, tail, workspace, approvedHandoff, linked,
          generation, roundtrip, ready, humanAllows, grants, corrupted
vars == <<started, indexed, tail, workspace, approvedHandoff, linked,
          generation, roundtrip, ready, humanAllows, grants, corrupted>>
Init == /\ started = {} /\ indexed = {} /\ tail = {}
        /\ workspace = [s \in Sessions |-> 1]
        /\ approvedHandoff = {} /\ linked = {}
        /\ generation = 0 /\ roundtrip = [s \in Sessions |-> -1]
        /\ ready = {} /\ humanAllows = {} /\ grants = {} /\ corrupted = FALSE
Start(s) == /\ s \notin started
            /\ started' = started \cup {s} /\ tail' = tail \cup {s}
            /\ UNCHANGED <<indexed, workspace, approvedHandoff, linked,
                           generation, roundtrip, ready, humanAllows, grants, corrupted>>
Index(s) == /\ s \in started /\ s \notin indexed
            /\ indexed' = indexed \cup {s}
            /\ UNCHANGED <<started, tail, workspace, approvedHandoff, linked,
                           generation, roundtrip, ready, humanAllows, grants, corrupted>>
Evict == /\ tail # {} /\ tail' = {}
         /\ UNCHANGED <<started, indexed, workspace, approvedHandoff, linked,
                        generation, roundtrip, ready, humanAllows, grants, corrupted>>
Corrupt == /\ ~corrupted /\ indexed # {}
           /\ indexed' = {} /\ ready' = {} /\ corrupted' = TRUE
           /\ UNCHANGED <<started, tail, workspace, approvedHandoff, linked,
                          generation, roundtrip, humanAllows, grants>>
ApproveHandoff(s) == /\ s \notin approvedHandoff
                    /\ approvedHandoff' = approvedHandoff \cup {s}
                    /\ UNCHANGED <<started, indexed, tail, workspace, linked,
                                   generation, roundtrip, ready, humanAllows, grants, corrupted>>
Handoff(s) == /\ s \in approvedHandoff /\ workspace[s] = 1
              /\ workspace' = [workspace EXCEPT ![s] = 2]
              /\ roundtrip' = [roundtrip EXCEPT ![s] = -1]
              /\ ready' = ready \ {s}
              /\ grants' = IF CopyAuthorityBug /\ <<s, 1>> \in grants
                            THEN grants \cup {<<s, 2>>} ELSE grants
              /\ UNCHANGED <<started, indexed, tail, approvedHandoff, linked,
                             generation, humanAllows, corrupted>>
PublishLink(s) == /\ workspace[s] = 2 /\ s \in approvedHandoff /\ s \notin linked
                  /\ linked' = linked \cup {s}
                  /\ UNCHANGED <<started, indexed, tail, workspace, approvedHandoff,
                                 generation, roundtrip, ready, humanAllows, grants, corrupted>>
Upgrade == /\ generation = 0 /\ generation' = 1 /\ ready' = {}
           /\ UNCHANGED <<started, indexed, tail, workspace, approvedHandoff,
                          linked, roundtrip, humanAllows, grants, corrupted>>
Roundtrip(s) == /\ roundtrip[s] # generation
                /\ roundtrip' = [roundtrip EXCEPT ![s] = generation]
                /\ UNCHANGED <<started, indexed, tail, workspace, approvedHandoff,
                               linked, generation, ready, humanAllows, grants, corrupted>>
Observe(s) == /\ s \in indexed /\ roundtrip[s] = generation
              /\ (workspace[s] = 1 \/ s \in linked) /\ s \notin ready
              /\ ready' = ready \cup {s}
              /\ UNCHANGED <<started, indexed, tail, workspace, approvedHandoff,
                             linked, generation, roundtrip, humanAllows, grants, corrupted>>
HumanAllow(s) == /\ <<s, workspace[s]>> \notin humanAllows
                 /\ humanAllows' = humanAllows \cup {<<s, workspace[s]>>}
                 /\ grants' = grants \cup {<<s, workspace[s]>>}
                 /\ UNCHANGED <<started, indexed, tail, workspace, approvedHandoff,
                                linked, generation, roundtrip, ready, corrupted>>
Next == Evict \/ Corrupt \/ Upgrade \/
        (\E s \in Sessions: Start(s) \/ Index(s) \/ ApproveHandoff(s) \/ Handoff(s)
          \/ PublishLink(s) \/ Roundtrip(s) \/ Observe(s) \/ HumanAllow(s))
Spec == Init /\ [][Next]_vars /\
        (\A s \in Sessions: WF_vars(Index(s)) /\ WF_vars(PublishLink(s))
          /\ WF_vars(Roundtrip(s)) /\ WF_vars(Observe(s)))
NoInventedStart == indexed \subseteq started
NoAuthorityTransfer == grants \subseteq humanAllows
TruthfulReadiness == \A s \in ready:
                      s \in indexed /\ roundtrip[s] = generation
                      /\ (workspace[s] = 1 \/ s \in linked)
EventuallyObservable == \A s \in Sessions: (s \in started) ~> (s \in ready)
=============================================================================
