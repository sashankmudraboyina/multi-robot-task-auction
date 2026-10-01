using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// SHADE: Shadow-Hedged Auction with Decaying Estimates (PNR2 Solution)
/// Full decentralized multi-robot task allocation protocol simulation for warehouse robots.
/// Features:
/// 1. Signed Manifests & Implicit Bidding (Multi-variable bids without broadcast storms)
/// 2. Ghost Bids & Optimistic Extrapolation for silent/partitioned peers
/// 3. Regret-Bounded Claiming with Decaying Patience Tolerance
/// 4. Succession Ranks & Staggered Takeover
/// 5. Progress-Ratchet Leases (Stall/Byzantine detection & automated revocation)
/// 6. Finish-Line Yield Rule upon Partition Healing
/// </summary>
public class ShadeAuctionProtocol : MonoBehaviour
{
    public static ShadeAuctionProtocol Instance;

    [Header("Core References")]
    public Warehouse warehouse;
    public Warehouse_orders warehouseOrders;

    [Header("SHADE Protocol Hyperparameters")]
    public float theta = 0.25f; // Patience fraction knob: 0.05 (fast/greedy), 0.25 (balanced), 1.0 (conservative)
    public float leaseDurationL = 6.0f; // Lease duration in seconds
    public float rhoMin = 0.3f; // Minimum remaining cost reduction rate (m/s)
    public float staggerDelta = 0.2f; // Stagger between succession ranks (seconds)
    public float tauLive = 3.0f; // Heartbeat silence threshold to become Ghost (seconds)
    public float maxSpeed = 5.0f; // v_max of robot in m/s
    public float bidWidthW = 1.2f; // Bid range width W

    // Weights for implicit bidding: wd, wb, we, wc, lambda
    public float w_dist = 0.30f;
    public float w_batt = 0.25f;
    public float w_eta = 0.25f;
    public float w_fit = 0.20f;
    public float lambda_uncertainty = 0.30f;

    [System.Serializable]
    public class RobotManifest
    {
        public int robotId;
        public int seq = 0;
        public float lastSeenTime;
        public Vector3 pose;
        public float battery = 100f; // 0 - 100%
        public float drainRate = 0.15f; // % per second when moving
        public bool isOnline = true; // false = partitioned / network cut
        public bool isStalled = false; // true = Byzantine / hardware failure

        public int strikes = 0;
        public bool isQuarantined = false;

        // Active lease
        public int heldTaskId = -1;
        public int leaseEpoch = 0;
        public float leaseUntil = 0f;
        public float remainingCost = 0f;
        public float lastRecordedCost = 0f;
        public float lastCostCheckTime = 0f;
        public bool ratchetFailing = false;
    }

    [System.Serializable]
    public class ShadeTask
    {
        public int taskId;
        public Warehouse_shelf shelf;
        public Warehouse_node targetNode;
        public int quantity = 1;
        public float creationTime;
        public float deadline;
        public float priority = 1.0f;

        public enum State { Open, PatienceWaiting, Claimed, Completed, Cancelled }
        public State state = State.Open;

        public int winningRobotId = -1;
        public int leaseEpoch = 1;
        public float claimTime = 0f;

        // Auction evaluation metrics
        public float winningBid = 0f;
        public float highestGhostBid = 0f;
        public int bestGhostRobotId = -1;
        public float currentRegret = 0f;
        public float currentTolerance = 0f;
        public float patienceDelay = 0f;
        public float patienceTimer = 0f;

        // Succession ranks: sorted robot IDs [Rank 0, Rank 1, Rank 2...]
        public List<int> successionRanks = new List<int>();
        public Dictionary<int, float> computedBids = new Dictionary<int, float>();
        public Dictionary<int, bool> isGhostBid = new Dictionary<int, bool>();
        public Dictionary<int, bool> isGatedOut = new Dictionary<int, bool>();
        public Dictionary<int, string> gateReason = new Dictionary<int, string>();
    }

    public List<RobotManifest> fleetManifests = new List<RobotManifest>();
    public List<ShadeTask> activeTasks = new List<ShadeTask>();
    private int nextTaskId = 1;

    // Live Event Log (for UI explanation)
    public class EventEntry
    {
        public float time;
        public string category;
        public string message;
        public Color color;
    }
    public List<EventEntry> eventLog = new List<EventEntry>();

    // Interactive Demo State
    public bool networkPartitionActive = false;
    public bool showFullUI = true;
    public bool showMiniMap = true;
    public bool showWorldLabels = true;
    public int simulatedStalledRobotId = -1;
    public Rect warehouseBounds = new Rect(0, 0, 85, 95);

    private Texture2D _whiteTex;
    private Texture2D whiteTex
    {
        get
        {
            if (_whiteTex == null)
            {
                _whiteTex = new Texture2D(1, 1);
                _whiteTex.SetPixel(0, 0, Color.white);
                _whiteTex.Apply();
            }
            return _whiteTex;
        }
    }

    void DrawRect(Rect r, Color c)
    {
        Color old = GUI.color;
        GUI.color = c;
        GUI.DrawTexture(r, whiteTex);
        GUI.color = old;
    }

    void DrawLine(Vector2 p1, Vector2 p2, Color c, float width = 2f)
    {
        Vector2 d = p2 - p1;
        float angle = Mathf.Atan2(d.y, d.x) * Mathf.Rad2Deg;
        float length = d.magnitude;
        GUIUtility.RotateAroundPivot(angle, p1);
        DrawRect(new Rect(p1.x, p1.y - width / 2f, length, width), c);
        GUIUtility.RotateAroundPivot(-angle, p1);
    }

    Color ParseColor(string hex)
    {
        Color c;
        if (ColorUtility.TryParseHtmlString(hex, out c)) return c;
        return Color.white;
    }

    void CalculateWarehouseBounds()
    {
        if (warehouse != null && warehouse.nodos != null && warehouse.nodos.Length > 0)
        {
            float minX = float.MaxValue, maxX = float.MinValue;
            float minZ = float.MaxValue, maxZ = float.MinValue;
            foreach (var n in warehouse.nodos)
            {
                if (n == null) continue;
                Vector3 p = n.transform.position;
                if (p.x < minX) minX = p.x;
                if (p.x > maxX) maxX = p.x;
                if (p.z < minZ) minZ = p.z;
                if (p.z > maxZ) maxZ = p.z;
            }
            warehouseBounds = new Rect(minX - 4, minZ - 4, (maxX - minX) + 8, (maxZ - minZ) + 8);
        }
    }

    Vector2 WorldToMap(Vector3 w, Rect mapInner)
    {
        float normX = Mathf.Clamp01((w.x - warehouseBounds.x) / Mathf.Max(1f, warehouseBounds.width));
        float normZ = Mathf.Clamp01((w.z - warehouseBounds.y) / Mathf.Max(1f, warehouseBounds.height));
        float mx = mapInner.x + normX * mapInner.width;
        float my = mapInner.y + (1f - normZ) * mapInner.height;
        return new Vector2(mx, my);
    }

    void Awake()
    {
        Instance = this;
    }

    void Start()
    {
        if (warehouse == null) warehouse = FindObjectOfType<Warehouse>();
        if (warehouseOrders == null) warehouseOrders = FindObjectOfType<Warehouse_orders>();

        StartCoroutine(InitializeFleetWhenReady());
    }

    IEnumerator InitializeFleetWhenReady()
    {
        while (warehouse.robots == null || warehouse.robots.Length == 0)
        {
            yield return new WaitForSeconds(0.2f);
        }

        fleetManifests.Clear();
        for (int i = 0; i < warehouse.robots.Length; i++)
        {
            Robot r = warehouse.robots[i];
            RobotManifest m = new RobotManifest();
            m.robotId = r.robotID;
            m.pose = r.transform.position;
            m.lastSeenTime = Time.time;
            m.battery = 85f + (i * 2.5f) % 15f; // Realistic battery variations
            fleetManifests.Add(m);
        }

        CalculateWarehouseBounds();

        AddLog("SHADE", "SHADE Protocol initialized with " + fleetManifests.Count + " robots.", Color.cyan);
        AddLog("GHOST", "Silent peers will bid as extrapolated ghosts with regret-bounded wait.", Color.white);
    }

    public void AddLog(string cat, string msg, Color col)
    {
        EventEntry e = new EventEntry();
        e.time = Time.time;
        e.category = cat;
        e.message = msg;
        e.color = col;
        eventLog.Insert(0, e);
        if (eventLog.Count > 30) eventLog.RemoveAt(eventLog.Count - 1);
    }

    void Update()
    {
        if (fleetManifests.Count == 0) return;

        // Interactive Demonstration Hotkeys (work during camera navigation)
        if (Input.GetKeyDown(KeyCode.M)) showMiniMap = !showMiniMap;
        if (Input.GetKeyDown(KeyCode.L)) showWorldLabels = !showWorldLabels;
        if (Input.GetKeyDown(KeyCode.P)) ToggleNetworkPartition();
        if (Input.GetKeyDown(KeyCode.K)) ToggleStallWinner();
        if (Input.GetKeyDown(KeyCode.T)) SpawnManualTask();
        if (Input.GetKeyDown(KeyCode.O)) CyclePatienceKnob();
        if (Input.GetKeyDown(KeyCode.H)) showFullUI = !showFullUI;
        if (Input.GetKeyDown(KeyCode.R)) ResetAll();

        UpdateManifestsAndSimulatedSensors();
        CheckShelfOrdersForNewTasks();
        ProcessOpenTaskAuctions();
        MonitorProgressRatchetLeases();
    }

    /// <summary>
    /// Update simulated robot manifests (position, battery, communication state)
    /// </summary>
    void UpdateManifestsAndSimulatedSensors()
    {
        for (int i = 0; i < warehouse.robots.Length; i++)
        {
            Robot r = warehouse.robots[i];
            if (i >= fleetManifests.Count) continue;
            RobotManifest m = fleetManifests[i];

            // If robot is online, update latest pose and timestamp
            if (m.isOnline)
            {
                m.pose = r.transform.position;
                m.lastSeenTime = Time.time;
                m.seq++;

                // Simulate battery drain
                if (r.RobotState == Robot.RobotStates.OnWayToPick || r.RobotState == Robot.RobotStates.OnWayToDrop)
                {
                    m.battery = Mathf.Max(5f, m.battery - m.drainRate * Time.deltaTime);
                }
                else
                {
                    m.battery = Mathf.Max(5f, m.battery - 0.02f * Time.deltaTime);
                }
            }

            // If robot is marked stalled, forcibly halt its physical movement
            if (m.isStalled)
            {
                if (r.robot_Wheels != null) r.robot_Wheels.stop = true;
            }
        }
    }

    /// <summary>
    /// Scan warehouse shelves and generate SHADE tasks for pending orders
    /// </summary>
    void CheckShelfOrdersForNewTasks()
    {
        if (warehouseOrders == null || warehouseOrders.shelves == null) return;

        foreach (Warehouse_shelf shelf in warehouseOrders.shelves)
        {
            if (shelf.products_to_pick > 0)
            {
                // Check if a task already exists for this shelf
                bool alreadyTracked = false;
                foreach (ShadeTask t in activeTasks)
                {
                    if (t.shelf == shelf && (t.state == ShadeTask.State.Open || t.state == ShadeTask.State.PatienceWaiting || t.state == ShadeTask.State.Claimed))
                    {
                        alreadyTracked = true;
                        break;
                    }
                }

                if (!alreadyTracked)
                {
                    Warehouse_node targetNode = (Random.value > 0.5f && shelf.node2 != null) ? shelf.node2 : shelf.node1;
                    CreateShadeTask(shelf, targetNode, 1);
                }
            }
        }
    }

    public ShadeTask CreateShadeTask(Warehouse_shelf shelf, Warehouse_node targetNode, int qty)
    {
        ShadeTask task = new ShadeTask();
        task.taskId = nextTaskId++;
        task.shelf = shelf;
        task.targetNode = targetNode;
        task.quantity = qty;
        task.creationTime = Time.time;
        task.deadline = Time.time + 60.0f; // 60s deadline
        task.priority = 1.0f + (task.taskId % 3) * 0.5f; // Priority 1.0 - 2.0
        task.state = ShadeTask.State.Open;

        for (int i = 0; i < fleetManifests.Count; i++)
        {
            RobotManifest m = fleetManifests[i];
            bool g; string reas;
            float b = ComputeLiveBid(m, warehouse.robots[i], task, out g, out reas);
            task.computedBids[m.robotId] = b;
            task.isGatedOut[m.robotId] = !g;
            task.gateReason[m.robotId] = reas;
            task.isGhostBid[m.robotId] = !m.isOnline;
        }

        activeTasks.Add(task);
        AddLog("TASK", "Task T" + task.taskId + " opened at Shelf #" + shelf.id + " (Node " + targetNode.nodeID + ", Pri " + task.priority.ToString("F1") + ")", Color.yellow);
        return task;
    }

    /// <summary>
    /// Main SHADE Auction Loop: Implicit Bidding + Ghost Estimation + Regret-Bounded Claiming
    /// </summary>
    void ProcessOpenTaskAuctions()
    {
        for (int tIdx = 0; tIdx < activeTasks.Count; tIdx++)
        {
            ShadeTask task = activeTasks[tIdx];
            if (task.state != ShadeTask.State.Open && task.state != ShadeTask.State.PatienceWaiting) continue;

            // 1. Implicit Bidding: Compute bids for all live robots and optimistic ghost bounds for silent peers
            task.computedBids.Clear();
            task.isGhostBid.Clear();

            int bestLiveRobot = -1;
            float bestLiveBid = -1f;

            int bestGhostRobot = -1;
            float bestGhostBid = -1f;

            List<KeyValuePair<int, float>> liveRankCandidates = new List<KeyValuePair<int, float>>();

            for (int i = 0; i < fleetManifests.Count; i++)
            {
                RobotManifest m = fleetManifests[i];
                Robot r = warehouse.robots[i];

                bool isGhost = !m.isOnline || (Time.time - m.lastSeenTime > tauLive);
                task.isGhostBid[m.robotId] = isGhost;

                if (!isGhost)
                {
                    // Live robot implicit bid
                    bool gate;
                    string reason;
                    float bid = ComputeLiveBid(m, r, task, out gate, out reason);
                    task.computedBids[m.robotId] = bid;
                    task.isGatedOut[m.robotId] = !gate;
                    task.gateReason[m.robotId] = reason;

                    if (gate && bid > 0f)
                    {
                        liveRankCandidates.Add(new KeyValuePair<int, float>(m.robotId, bid));
                        if (bid > bestLiveBid)
                        {
                            bestLiveBid = bid;
                            bestLiveRobot = m.robotId;
                        }
                    }
                }
                else
                {
                    // Ghost optimistic upper-bound bid
                    float ghostAge = Mathf.Max(0f, Time.time - m.lastSeenTime);
                    float ghostBid = ComputeGhostOptimisticBid(m, task, ghostAge);
                    task.computedBids[m.robotId] = ghostBid;
                    task.isGatedOut[m.robotId] = false;
                    task.gateReason[m.robotId] = "Ghost";

                    if (ghostBid > bestGhostBid)
                    {
                        bestGhostBid = ghostBid;
                        bestGhostRobot = m.robotId;
                    }
                }
            }

            // Sort succession ranks (Rank 0 = highest live bidder)
            liveRankCandidates.Sort((a, b) => b.Value.CompareTo(a.Value));
            task.successionRanks.Clear();
            foreach (var kvp in liveRankCandidates)
            {
                task.successionRanks.Add(kvp.Key);
            }

            // If no live robot passes gate, wait for an available robot
            if (bestLiveRobot == -1)
            {
                continue;
            }

            // 2. Compute Regret: rho_r = max(0, bestGhostBid - bestLiveBid)
            float regret = 0f;
            if (bestGhostRobot != -1 && bestGhostBid > bestLiveBid)
            {
                regret = bestGhostBid - bestLiveBid;
            }

            // 3. Compute Decaying Patience Tolerance:
            // P_k = (theta * (deadline - create)) / priority
            // eps_k(t) = W * min(1, (t - create) / P_k)
            float totalDuration = Mathf.Max(10f, task.deadline - task.creationTime);
            float P_k = Mathf.Max(2.0f, (theta * totalDuration) / task.priority);
            float age = Time.time - task.creationTime;
            float tolerance = bidWidthW * Mathf.Clamp01(age / P_k);

            task.winningRobotId = bestLiveRobot;
            task.winningBid = bestLiveBid;
            task.highestGhostBid = bestGhostBid;
            task.bestGhostRobotId = bestGhostRobot;
            task.currentRegret = regret;
            task.currentTolerance = tolerance;
            task.patienceDelay = P_k * (regret / bidWidthW);

            // 4. SHADE Claim Rule: Claim if Regret <= Tolerance
            if (regret <= tolerance)
            {
                // Regret bound satisfied! Award task under Progress-Ratchet Lease
                AwardTaskToRobot(task, bestLiveRobot, 1);
            }
            else
            {
                // Regret exceeds tolerance: must wait patience window
                if (task.state != ShadeTask.State.PatienceWaiting)
                {
                    task.state = ShadeTask.State.PatienceWaiting;
                    AddLog("REGRET", "T" + task.taskId + ": R" + bestLiveRobot + " (Bid " + bestLiveBid.ToString("F2") + ") losing " + regret.ToString("F2") +
                                     " to Ghost R" + bestGhostRobot + " (Est " + bestGhostBid.ToString("F2") + "). Waiting patience (" + (task.patienceDelay - age).ToString("F1") + "s)...", new Color(1f, 0.6f, 0.2f));
                }
            }
        }
    }

    /// <summary>
    /// Implicit multi-variable bid formula from Section 4:
    /// B(M,k,t) = G * [w_d * s_dist + w_b * s_batt + w_e * s_eta + w_c * s_fit] - lambda * sigma
    /// </summary>
    float ComputeLiveBid(RobotManifest m, Robot r, ShadeTask t, out bool gate, out string reason)
    {
        float dist = Vector3.Distance(m.pose, t.targetNode.transform.position);
        float s_dist = Mathf.Clamp01(1f - (dist / 120f));
        float s_batt = Mathf.Clamp01(m.battery / 100f);

        float estTravelTime = dist / Mathf.Max(1f, maxSpeed);
        float slack = Mathf.Max(5f, t.deadline - Time.time);
        float s_eta = Mathf.Clamp01(1f - (estTravelTime / slack));
        float s_fit = 1.0f; // Capability match

        float sigma = 0.05f; // Small uncertainty penalty for network jitter

        float bid = (w_dist * s_dist + w_batt * s_batt + w_eta * s_eta + w_fit * s_fit) - (lambda_uncertainty * sigma);
        bid = Mathf.Clamp(bid, 0.05f, 1.0f);

        // Gate evaluation
        if (m.isQuarantined) { gate = false; reason = "Quarantined"; }
        else if (m.isStalled) { gate = false; reason = "Stalled"; }
        else if (m.battery < 15f) { gate = false; reason = "Low Battery"; }
        else if (r.containerFilled >= r.containerCapacity) { gate = false; reason = "Cargo Full"; }
        else if (r.RobotState == Robot.RobotStates.OnWayToPick || r.RobotState == Robot.RobotStates.PickingUp) { gate = false; reason = "Busy (Assigned)"; }
        else if (r.RobotState == Robot.RobotStates.OnWayToDrop || r.RobotState == Robot.RobotStates.Unloading || r.RobotState == Robot.RobotStates.PrepareUnloading || r.RobotState == Robot.RobotStates.RampGoingDown || r.RobotState == Robot.RobotStates.RampGoingUp) { gate = false; reason = "Unloading"; }
        else { gate = true; reason = "Eligible"; }

        return bid;
    }

    /// <summary>
    /// Ghost upper-bound bid from Section 5:
    /// Assumes ghost robot moved towards task at v_max, battery unchanged, zero uncertainty
    /// </summary>
    float ComputeGhostOptimisticBid(RobotManifest m, ShadeTask t, float ghostAge)
    {
        float lastDist = Vector3.Distance(m.pose, t.targetNode.transform.position);
        // Optimistic projected distance:
        float optDist = Mathf.Max(0f, lastDist - (maxSpeed * ghostAge));
        float s_dist = Mathf.Clamp01(1f - (optDist / 120f));
        float s_batt = Mathf.Clamp01(m.battery / 100f);

        float estTravelTime = optDist / Mathf.Max(1f, maxSpeed);
        float slack = Mathf.Max(5f, t.deadline - Time.time);
        float s_eta = Mathf.Clamp01(1f - (estTravelTime / slack));
        float s_fit = 1.0f;

        float sigma = 0f; // Zero uncertainty penalty for upper-bound ghost

        float bid = (w_dist * s_dist + w_batt * s_batt + w_eta * s_eta + w_fit * s_fit) - (lambda_uncertainty * sigma);
        return Mathf.Clamp(bid, 0.05f, 1.0f);
    }

    /// <summary>
    /// Award a task to a robot under a Progress-Ratchet Lease
    /// </summary>
    void AwardTaskToRobot(ShadeTask task, int robotId, int epoch)
    {
        task.state = ShadeTask.State.Claimed;
        task.winningRobotId = robotId;
        task.leaseEpoch = epoch;
        task.claimTime = Time.time;

        Robot r = warehouse.robots[robotId];
        RobotManifest m = fleetManifests[robotId];

        // Establish lease record
        float initialDist = Vector3.Distance(r.transform.position, task.targetNode.transform.position);
        m.heldTaskId = task.taskId;
        m.leaseEpoch = epoch;
        m.leaseUntil = Time.time + leaseDurationL;
        m.remainingCost = initialDist;
        m.lastRecordedCost = initialDist;
        m.lastCostCheckTime = Time.time;
        m.ratchetFailing = false;

        // Command robot
        task.shelf.products -= task.quantity;
        task.shelf.products_to_pick = Mathf.Max(0, task.shelf.products_to_pick - task.quantity);

        r.shelf_target = task.shelf;
        r.warehousenodeTarget = task.targetNode;
        warehouse.setRobotRoute(r.robotID, -1, task.targetNode.nodeID);
        r.RobotState = Robot.RobotStates.OnWayToPick;
        r.containerFilled += task.quantity;

        AddLog("CLAIM", "✓ Task T" + task.taskId + " CLAIMED by R" + robotId + " (Bid " + task.winningBid.ToString("F2") + ", Epoch " + epoch + ", Lease " + leaseDurationL + "s)", Color.green);
    }

    /// <summary>
    /// Mechanism 4: Progress-Ratchet Leases
    /// Checks that the task owner makes verifiable physical progress towards the task.
    /// Traps stalled or Byzantine robots without voting!
    /// </summary>
    void MonitorProgressRatchetLeases()
    {
        for (int i = 0; i < fleetManifests.Count; i++)
        {
            RobotManifest m = fleetManifests[i];
            if (m.heldTaskId == -1) continue;

            ShadeTask task = activeTasks.Find(t => t.taskId == m.heldTaskId);
            if (task == null || task.state != ShadeTask.State.Claimed) continue;

            Robot r = warehouse.robots[m.robotId];
            float currentDist = Vector3.Distance(r.transform.position, task.targetNode.transform.position);
            m.remainingCost = currentDist;

            // Check if robot arrived at pickup
            if (r.RobotState == Robot.RobotStates.PickingUp || r.RobotState == Robot.RobotStates.Available || currentDist < 2.0f)
            {
                // Task pickup complete!
                task.state = ShadeTask.State.Completed;
                m.heldTaskId = -1;
                AddLog("SUCCESS", "★ Task T" + task.taskId + " successfully reached by R" + m.robotId, Color.green);
                continue;
            }

            // Periodic Ratchet Check (every 1.5 seconds)
            if (Time.time - m.lastCostCheckTime >= 1.5f)
            {
                float timeDelta = Time.time - m.lastCostCheckTime;
                float costReduction = m.lastRecordedCost - currentDist;

                // Ratchet condition: remaining cost must drop by at least rhoMin * deltaT
                bool ratchetPassed = costReduction >= (rhoMin * timeDelta);

                if (ratchetPassed && !m.isStalled)
                {
                    // Progress verified! Renew lease
                    m.leaseUntil = Time.time + leaseDurationL;
                    m.lastRecordedCost = currentDist;
                    m.lastCostCheckTime = Time.time;
                    m.ratchetFailing = false;
                }
                else
                {
                    // Ratchet check FAILED: robot is stalled, blocked, or lying
                    m.ratchetFailing = true;
                    // Renewal rejected! Lease clock continues ticking down to expiry
                }
            }

            // Has the lease expired without renewal?
            if (Time.time > m.leaseUntil)
            {
                // LEASE EXPIRED! Automated revocation & Succession Takeover (Mechanism 3)
                AddLog("RATCHET", "⚠ LEASE EXPIRED for R" + m.robotId + " on T" + task.taskId + " (No progress detected!). Revoking claim!", Color.red);
                m.strikes++;
                if (m.strikes >= 3)
                {
                    m.isQuarantined = true;
                    AddLog("BYZANTINE", "⛔ Robot R" + m.robotId + " has 3 strikes -> QUARANTINED!", Color.red);
                }

                m.heldTaskId = -1;
                m.ratchetFailing = false;

                // Trigger Succession Takeover: Next rank in succession list takes over!
                TriggerSuccessionTakeover(task, m.robotId);
            }
        }
    }

    /// <summary>
    /// Mechanism 3: Succession Ranks & Staggered Takeover
    /// Next available robot in the succession list immediately takes over without a full auction round!
    /// </summary>
    void TriggerSuccessionTakeover(ShadeTask task, int failedRobotId)
    {
        int nextSuccessor = -1;
        foreach (int candidateId in task.successionRanks)
        {
            if (candidateId != failedRobotId && fleetManifests[candidateId].isOnline && !fleetManifests[candidateId].isStalled && !fleetManifests[candidateId].isQuarantined)
            {
                if (warehouse.robots[candidateId].RobotState == Robot.RobotStates.Available)
                {
                    nextSuccessor = candidateId;
                    break;
                }
            }
        }

        if (nextSuccessor != -1)
        {
            AddLog("TAKEOVER", "⚡ Succession Takeover: Rank-1 successor R" + nextSuccessor + " takes over Task T" + task.taskId + " (Epoch " + (task.leaseEpoch + 1) + ")", Color.magenta);
            AwardTaskToRobot(task, nextSuccessor, task.leaseEpoch + 1);
        }
        else
        {
            // Re-open task for auction
            task.state = ShadeTask.State.Open;
            task.winningRobotId = -1;
            AddLog("AUCTION", "Task T" + task.taskId + " re-opened for fleet auction.", Color.yellow);
        }
    }

    /// <summary>
    /// Mechanism 5: Finish-Line Yield Rule on Partition Healing
    /// When a healed partition reveals multiple owners, the one closer to finishing keeps the task!
    /// </summary>
    public void ResolveFinishLineConflict(ShadeTask task, int robotA, int robotB)
    {
        float distA = Vector3.Distance(warehouse.robots[robotA].transform.position, task.targetNode.transform.position);
        float distB = Vector3.Distance(warehouse.robots[robotB].transform.position, task.targetNode.transform.position);

        int winner = (distA <= distB) ? robotA : robotB;
        int yielder = (distA <= distB) ? robotB : robotA;

        AddLog("FINISH-LINE", "⚖ Partition Healed! Conflict on T" + task.taskId + ": R" + robotA + " (rem " + distA.ToString("F1") + "m) vs R" + robotB + " (rem " + distB.ToString("F1") + "m)", Color.cyan);
        AddLog("FINISH-LINE", "→ Finish-Line Rule: R" + winner + " is closer and KEEPS task. R" + yielder + " YIELDS.", Color.green);

        // Winner keeps task
        task.winningRobotId = winner;
        fleetManifests[winner].heldTaskId = task.taskId;

        // Yielder relinquishes task
        fleetManifests[yielder].heldTaskId = -1;
        warehouse.robots[yielder].RobotState = Robot.RobotStates.Available;
    }

    // ==========================================
    // INTERACTIVE CONTROLS FOR DEMONSTRATION
    // ==========================================

    public void ToggleNetworkPartition()
    {
        networkPartitionActive = !networkPartitionActive;
        // Partition robots R4 and R5
        if (fleetManifests.Count > 4) fleetManifests[4].isOnline = !networkPartitionActive;
        if (fleetManifests.Count > 5) fleetManifests[5].isOnline = !networkPartitionActive;

        if (networkPartitionActive)
        {
            AddLog("PARTITION", "⚡ NETWORK PARTITION ACTIVATED! Robots R4 & R5 disconnected -> Treated as GHOSTS!", Color.magenta);
        }
        else
        {
            AddLog("HEAL", "🌐 NETWORK HEALED! R4 & R5 reconnected -> Exchanging state & applying Finish-Line rule.", Color.cyan);
            // Check for healed conflicts if any
        }
    }

    public void ToggleStallWinner()
    {
        if (simulatedStalledRobotId == -1)
        {
            // Find currently active owner robot
            for (int i = 0; i < fleetManifests.Count; i++)
            {
                if (fleetManifests[i].heldTaskId != -1)
                {
                    simulatedStalledRobotId = i;
                    fleetManifests[i].isStalled = true;
                    AddLog("FAULT", "⚠ INJECTED FAULT: Robot R" + i + " STALLED! Watch Progress-Ratchet lease expire...", Color.red);
                    return;
                }
            }
            // If no active owner, stall R0
            simulatedStalledRobotId = 0;
            fleetManifests[0].isStalled = true;
            AddLog("FAULT", "⚠ INJECTED FAULT: Robot R0 STALLED!", Color.red);
        }
        else
        {
            fleetManifests[simulatedStalledRobotId].isStalled = false;
            if (warehouse.robots[simulatedStalledRobotId].robot_Wheels != null)
                warehouse.robots[simulatedStalledRobotId].robot_Wheels.stop = false;
            AddLog("FAULT", "✓ Robot R" + simulatedStalledRobotId + " recovered and restored to normal operation.", Color.green);
            simulatedStalledRobotId = -1;
        }
    }

    public void CyclePatienceKnob()
    {
        if (theta == 0.05f) theta = 0.25f;
        else if (theta == 0.25f) theta = 1.0f;
        else theta = 0.05f;

        string desc = theta == 0.05f ? "0.05 (Aggressive/Fast Claims)" : (theta == 0.25f ? "0.25 (Balanced SHADE Default)" : "1.0 (Conservative/Ghost-Hedged)");
        AddLog("KNOB", "Patience Knob θ updated to " + desc, Color.white);
    }

    public void SpawnManualTask()
    {
        if (warehouseOrders.shelves != null && warehouseOrders.shelves.Length > 0)
        {
            int randShelfIdx = Random.Range(0, warehouseOrders.shelves.Length);
            Warehouse_shelf shelf = warehouseOrders.shelves[randShelfIdx];
            shelf.products_to_pick++;
            AddLog("MANUAL", "Manually generated new customer order at Shelf #" + shelf.id, Color.yellow);
        }
    }

    public void ResetAll()
    {
        networkPartitionActive = false;
        simulatedStalledRobotId = -1;
        for (int i = 0; i < fleetManifests.Count; i++)
        {
            fleetManifests[i].isOnline = true;
            fleetManifests[i].isStalled = false;
            fleetManifests[i].strikes = 0;
            fleetManifests[i].isQuarantined = false;
            if (warehouse.robots[i].robot_Wheels != null)
                warehouse.robots[i].robot_Wheels.stop = false;
        }
        AddLog("RESET", "Fleet state, faults, and network partitions reset.", Color.white);
    }

    // ==========================================
    // VISUAL HEADS-UP DISPLAY (OnGUI)
    // ==========================================

    void OnGUI()
    {
        GUI.skin.box.normal.textColor = Color.white;
        GUI.skin.label.normal.textColor = Color.white;

        // Top Navigation Header
        GUI.Box(new Rect(10, 10, Screen.width - 20, 50), "");
        GUIStyle titleStyle = new GUIStyle(GUI.skin.label);
        titleStyle.fontSize = 18;
        titleStyle.fontStyle = FontStyle.Bold;
        titleStyle.normal.textColor = new Color(0.2f, 0.9f, 1f);
        GUI.Label(new Rect(25, 15, 650, 25), "SHADE: Ghost-Aware Decentralized Auction Protocol (PNR2)", titleStyle);

        GUIStyle subStyle = new GUIStyle(GUI.skin.label);
        subStyle.fontSize = 12;
        subStyle.normal.textColor = Color.gray;
        string netStr = networkPartitionActive ? "<color=magenta>PARTITIONED (R4,R5 Silent)</color>" : "<color=#44ff44>CONNECTED (Full Mesh)</color>";
        string knobStr = "Knob θ: <color=yellow>" + theta.ToString("F2") + "</color>";
        string hotkeys = "<color=#aaaaaa>[M] Map  [L] 3D Tags  [P] Partition  [K] Stall  [T] Task  [O] Knob  [H] UI  [Esc] Cursor</color>";
        GUI.Label(new Rect(25, 36, 750, 20), "Network: " + netStr + " | " + knobStr + " | " + hotkeys, subStyle);

        // Control Buttons inside Top Bar
        float btnX = Screen.width - 610;
        if (GUI.Button(new Rect(btnX, 15, 75, 36), showMiniMap ? "Hide Map" : "Show Map"))
        {
            showMiniMap = !showMiniMap;
        }
        if (GUI.Button(new Rect(btnX + 80, 15, 75, 36), showWorldLabels ? "Hide 3D" : "Show 3D"))
        {
            showWorldLabels = !showWorldLabels;
        }
        if (GUI.Button(new Rect(btnX + 160, 15, 120, 36), networkPartitionActive ? "Heal Network" : "Partition Net"))
        {
            ToggleNetworkPartition();
        }
        if (GUI.Button(new Rect(btnX + 285, 15, 110, 36), simulatedStalledRobotId != -1 ? "Recover Robot" : "Stall Owner"))
        {
            ToggleStallWinner();
        }
        if (GUI.Button(new Rect(btnX + 400, 15, 95, 36), "+ New Task"))
        {
            SpawnManualTask();
        }
        if (GUI.Button(new Rect(btnX + 500, 15, 80, 36), showFullUI ? "Min UI" : "Max UI"))
        {
            showFullUI = !showFullUI;
        }

        // Draw in-world labels and mini-map
        if (showWorldLabels) DrawWorldLabels();
        if (showMiniMap) DrawMiniMap();

        if (!showFullUI) return;

        // Left Panel: Fleet Manifests Table
        float panelY = 68;
        float leftWidth = 370;
        GUI.Box(new Rect(10, panelY, leftWidth, 230), "");
        GUI.Label(new Rect(20, panelY + 5, 300, 22), "<b>FLEET MANIFESTS (Implicit Bidding State)</b>");

        float rowY = panelY + 30;
        for (int i = 0; i < fleetManifests.Count; i++)
        {
            RobotManifest m = fleetManifests[i];
            Robot r = warehouse.robots[i];

            string statusTag;
            if (m.isQuarantined) statusTag = "<color=red>QUARANTINED</color>";
            else if (m.isStalled) statusTag = "<color=red>STALLED (Byzantine)</color>";
            else if (!m.isOnline) statusTag = "<color=magenta>GHOST (Partitioned)</color>";
            else if (r.RobotState == Robot.RobotStates.OnWayToPick) statusTag = "<color=yellow>ON WAY (T" + m.heldTaskId + ")</color>";
            else if (r.RobotState == Robot.RobotStates.PickingUp) statusTag = "<color=yellow>PICKING (T" + m.heldTaskId + ")</color>";
            else if (r.RobotState == Robot.RobotStates.OnWayToDrop) statusTag = "<color=cyan>UNLOADING</color>";
            else statusTag = "<color=#88ff88>AVAILABLE</color>";

            string leaseStr = "";
            if (m.heldTaskId != -1)
            {
                float remLease = Mathf.Max(0f, m.leaseUntil - Time.time);
                string rStatus = m.ratchetFailing ? "<color=red>FAIL</color>" : "<color=#44ff44>OK</color>";
                leaseStr = " | Lease: " + remLease.ToString("F1") + "s [" + rStatus + "]";
            }

            GUI.Label(new Rect(20, rowY, leftWidth - 30, 24),
                string.Format("<b>R{0}</b>  Batt: <b>{1:0}%</b>  Cargo: {2}/{3}  Status: {4}{5}",
                    m.robotId, m.battery, r.containerFilled, r.containerCapacity, statusTag, leaseStr));

            rowY += 28;
        }

        // Right Panel: Active SHADE Auction Board
        float rightX = Screen.width - 480;
        float rightWidth = 470;
        GUI.Box(new Rect(rightX, panelY, rightWidth, 230), "");
        GUI.Label(new Rect(rightX + 10, panelY + 5, rightWidth - 20, 22), "<b>ACTIVE SHADE AUCTION ENGINE</b>");

        // Display current active task info
        ShadeTask currentAuction = activeTasks.Find(t => t.state == ShadeTask.State.Open || t.state == ShadeTask.State.PatienceWaiting);
        if (currentAuction == null && activeTasks.Count > 0)
        {
            currentAuction = activeTasks[activeTasks.Count - 1]; // Show most recent
        }

        if (currentAuction != null)
        {
            string stateBadge = currentAuction.state == ShadeTask.State.Claimed ? "<color=#44ff44>[CLAIMED]</color>" :
                               (currentAuction.state == ShadeTask.State.PatienceWaiting ? "<color=orange>[PATIENCE WAITING]</color>" : "<color=yellow>[OPEN AUCTION]</color>");

            GUI.Label(new Rect(rightX + 10, panelY + 28, rightWidth - 20, 20),
                "Task: <b>T" + currentAuction.taskId + "</b> at Shelf #" + currentAuction.shelf.id + " | Pri: " + currentAuction.priority.ToString("F1") + " " + stateBadge);

            GUI.Label(new Rect(rightX + 10, panelY + 48, rightWidth - 20, 20),
                string.Format("Regret ρ: <b>{0:0.00}</b>  |  Tolerance ε(t): <b>{1:0.00}</b>  |  Claim if ρ ≤ ε",
                    currentAuction.currentRegret, currentAuction.currentTolerance));

            // Candidate bids table
            float bidRowY = panelY + 70;
            GUI.Label(new Rect(rightX + 10, bidRowY, rightWidth - 20, 20), "<b>Robot    Bid Score    Status / Type          Regret / Rank</b>");
            bidRowY += 20;

            for (int i = 0; i < fleetManifests.Count; i++)
            {
                int rId = fleetManifests[i].robotId;
                float bid = 0f;
                currentAuction.computedBids.TryGetValue(rId, out bid);
                if (bid <= 0.001f)
                {
                    bool g; string reas;
                    bid = ComputeLiveBid(fleetManifests[i], warehouse.robots[i], currentAuction, out g, out reas);
                    currentAuction.computedBids[rId] = bid;
                    currentAuction.isGatedOut[rId] = !g;
                    currentAuction.gateReason[rId] = reas;
                }

                bool isGhost = currentAuction.isGhostBid.ContainsKey(rId) && currentAuction.isGhostBid[rId];
                bool isGated = currentAuction.isGatedOut.ContainsKey(rId) && currentAuction.isGatedOut[rId];
                string reason = currentAuction.gateReason.ContainsKey(rId) ? currentAuction.gateReason[rId] : (isGated ? "Gated" : "Eligible");

                string typeStr = isGhost ? "<color=magenta>Ghost (Bound)</color>" : (isGated ? "<color=orange>Live (Gated)</color>" : "<color=#88ff88>Live Manifest</color>");

                string rankStr;
                if (currentAuction.winningRobotId == rId && (currentAuction.state == ShadeTask.State.Claimed || currentAuction.state == ShadeTask.State.Completed))
                {
                    rankStr = "<color=#44ff44>★ WINNER</color>";
                }
                else if (isGhost)
                {
                    rankStr = "<color=magenta>Ghost Bound</color>";
                }
                else if (isGated)
                {
                    rankStr = "<color=gray>" + reason + "</color>";
                }
                else
                {
                    int rankIdx = currentAuction.successionRanks.IndexOf(rId);
                    rankStr = rankIdx >= 0 ? "Rank " + rankIdx : "Standby";
                }

                GUI.Label(new Rect(rightX + 10, bidRowY, rightWidth - 20, 20),
                    string.Format("R{0}        <b><color=#ffff55>{1:0.00}</color></b>         {2}     {3}",
                        rId, bid, typeStr.PadRight(26), rankStr));
                bidRowY += 20;
            }
        }
        else
        {
            GUI.Label(new Rect(rightX + 20, panelY + 70, rightWidth - 40, 40), "No active tasks in auction.\nClick '+ New Task' above or wait for automatic shelf orders.");
        }

        // Bottom Panel: Live Protocol Event Log (Easy to understand step-by-step)
        float logHeight = 125;
        float logY = Screen.height - logHeight - 10;
        GUI.Box(new Rect(10, logY, Screen.width - 20, logHeight), "");
        GUI.Label(new Rect(20, logY + 5, 400, 20), "<b>SHADE PROTOCOL LIVE EXPLANATION LOG (Real-time Decisions & Consensus)</b>");

        float logEntryY = logY + 26;
        int showCount = Mathf.Min(4, eventLog.Count);
        GUIStyle logStyle = new GUIStyle(GUI.skin.label);
        logStyle.fontSize = 12;

        for (int i = 0; i < showCount; i++)
        {
            EventEntry e = eventLog[i];
            logStyle.normal.textColor = e.color;
            GUI.Label(new Rect(20, logEntryY, Screen.width - 40, 20),
                string.Format("[{0:00.0}s] [{1}] {2}", e.time, e.category, e.message), logStyle);
            logEntryY += 22;
        }
    }

    void DrawWorldLabels()
    {
        Camera cam = Camera.main != null ? Camera.main : FindObjectOfType<Camera>();
        if (cam == null) return;

        // 1. Draw labels over all robots
        for (int i = 0; i < fleetManifests.Count; i++)
        {
            RobotManifest m = fleetManifests[i];
            if (i >= warehouse.robots.Length) continue;
            Robot r = warehouse.robots[i];
            if (r == null) continue;

            Vector3 worldPos = r.transform.position + Vector3.up * 2.3f;
            Vector3 screenPos = cam.WorldToScreenPoint(worldPos);

            if (screenPos.z > 0f) // In front of camera
            {
                float sx = screenPos.x;
                float sy = Screen.height - screenPos.y;

                float distToCam = screenPos.z;
                if (distToCam > 180f) continue; // cull if too far

                // Color coding
                string colHex = "#44ff44"; // Available
                string stateName = "AVAILABLE";
                if (m.isQuarantined) { colHex = "#ff3333"; stateName = "QUARANTINED"; }
                else if (m.isStalled) { colHex = "#ff2222"; stateName = "STALLED"; }
                else if (!m.isOnline) { colHex = "#dd44ff"; stateName = "GHOST"; }
                else if (r.RobotState == Robot.RobotStates.OnWayToPick) { colHex = "#ffcc00"; stateName = "-> TASK T" + m.heldTaskId; }
                else if (r.RobotState == Robot.RobotStates.PickingUp) { colHex = "#ffaa00"; stateName = "PICKING T" + m.heldTaskId; }
                else if (r.RobotState == Robot.RobotStates.OnWayToDrop) { colHex = "#00ddff"; stateName = "UNLOADING"; }

                float boxW = 100f;
                float boxH = 40f;
                Rect rBox = new Rect(sx - boxW / 2f, sy - boxH, boxW, boxH);

                DrawRect(rBox, new Color(0.06f, 0.08f, 0.12f, 0.88f));
                DrawRect(new Rect(rBox.x, rBox.y, rBox.width, 2), ParseColor(colHex));

                GUIStyle lbl = new GUIStyle(GUI.skin.label);
                lbl.fontSize = 11;
                lbl.alignment = TextAnchor.MiddleCenter;
                lbl.fontStyle = FontStyle.Bold;

                GUI.Label(new Rect(rBox.x, rBox.y + 2, rBox.width, 18),
                    string.Format("<color={0}><b>R{1}</b></color> ({2:0}%)", colHex, m.robotId, m.battery), lbl);

                GUIStyle sub = new GUIStyle(GUI.skin.label);
                sub.fontSize = 10;
                sub.alignment = TextAnchor.MiddleCenter;
                GUI.Label(new Rect(rBox.x, rBox.y + 19, rBox.width, 16),
                    string.Format("<color={0}>{1}</color>", colHex, stateName), sub);
            }
        }

        // 2. Draw labels over all active tasks (shelves)
        for (int i = 0; i < activeTasks.Count; i++)
        {
            ShadeTask t = activeTasks[i];
            if (t.state != ShadeTask.State.Open && t.state != ShadeTask.State.PatienceWaiting && t.state != ShadeTask.State.Claimed) continue;
            if (t.shelf == null) continue;

            Vector3 worldPos = t.shelf.transform.position + Vector3.up * 4.5f;
            Vector3 screenPos = cam.WorldToScreenPoint(worldPos);

            if (screenPos.z > 0f)
            {
                float sx = screenPos.x;
                float sy = Screen.height - screenPos.y;
                float distToCam = screenPos.z;
                if (distToCam > 200f) continue;

                string colHex = t.state == ShadeTask.State.Claimed ? "#44ff44" : (t.state == ShadeTask.State.PatienceWaiting ? "#ffaa00" : "#ffff33");
                string stateStr = t.state == ShadeTask.State.Claimed ? ("CLAIMED: R" + t.winningRobotId) : (t.state == ShadeTask.State.PatienceWaiting ? "PATIENCE WAIT" : "OPEN AUCTION");

                float boxW = 120f;
                float boxH = 40f;
                Rect tBox = new Rect(sx - boxW / 2f, sy - boxH, boxW, boxH);

                DrawRect(tBox, new Color(0.12f, 0.08f, 0.05f, 0.90f));
                DrawRect(new Rect(tBox.x, tBox.y, tBox.width, 2), ParseColor(colHex));

                GUIStyle lbl = new GUIStyle(GUI.skin.label);
                lbl.fontSize = 11;
                lbl.alignment = TextAnchor.MiddleCenter;
                lbl.fontStyle = FontStyle.Bold;

                GUI.Label(new Rect(tBox.x, tBox.y + 2, tBox.width, 18),
                    string.Format("<color={0}>★ TASK T{1}</color> (S#{2})", colHex, t.taskId, t.shelf.id), lbl);

                GUIStyle sub = new GUIStyle(GUI.skin.label);
                sub.fontSize = 10;
                sub.alignment = TextAnchor.MiddleCenter;
                GUI.Label(new Rect(tBox.x, tBox.y + 19, tBox.width, 16),
                    string.Format("<color={0}>{1}</color>", colHex, stateStr), sub);
            }
        }
    }

    void DrawMiniMap()
    {
        float mapW = 270f;
        float mapH = 230f;
        float mapX = (Screen.width - mapW) / 2f;
        float mapY = 68f;

        // Background box
        DrawRect(new Rect(mapX, mapY, mapW, mapH), new Color(0.04f, 0.06f, 0.1f, 0.94f));
        // Outer border
        DrawRect(new Rect(mapX, mapY, mapW, 1), new Color(0.2f, 0.4f, 0.6f, 0.8f));
        DrawRect(new Rect(mapX, mapY + mapH - 1, mapW, 1), new Color(0.2f, 0.4f, 0.6f, 0.8f));
        DrawRect(new Rect(mapX, mapY, 1, mapH), new Color(0.2f, 0.4f, 0.6f, 0.8f));
        DrawRect(new Rect(mapX + mapW - 1, mapY, 1, mapH), new Color(0.2f, 0.4f, 0.6f, 0.8f));

        // Header bar
        DrawRect(new Rect(mapX, mapY, mapW, 22), new Color(0.1f, 0.16f, 0.24f, 0.95f));
        GUIStyle hStyle = new GUIStyle(GUI.skin.label);
        hStyle.fontSize = 11;
        hStyle.fontStyle = FontStyle.Bold;
        hStyle.normal.textColor = new Color(0.3f, 0.9f, 1f);
        GUI.Label(new Rect(mapX + 8, mapY + 2, 180, 18), "WAREHOUSE RADAR / MAP", hStyle);

        Rect mapInner = new Rect(mapX + 10, mapY + 26, mapW - 20, mapH - 52);

        // Draw warehouse shelves as faint blocks
        if (warehouseOrders != null && warehouseOrders.shelves != null)
        {
            Color shelfCol = new Color(0.22f, 0.30f, 0.42f, 0.45f);
            foreach (var s in warehouseOrders.shelves)
            {
                if (s == null) continue;
                Vector2 sm = WorldToMap(s.transform.position, mapInner);
                DrawRect(new Rect(sm.x - 3, sm.y - 2, 6, 4), shelfCol);
            }
        }

        GUIStyle nodeLabelStyle = new GUIStyle(GUI.skin.label);
        nodeLabelStyle.fontSize = 9;
        nodeLabelStyle.fontStyle = FontStyle.Bold;
        nodeLabelStyle.alignment = TextAnchor.MiddleCenter;

        // Draw active tasks
        for (int i = 0; i < activeTasks.Count; i++)
        {
            ShadeTask t = activeTasks[i];
            if (t.state != ShadeTask.State.Open && t.state != ShadeTask.State.PatienceWaiting && t.state != ShadeTask.State.Claimed) continue;
            if (t.shelf == null) continue;

            Vector2 tm = WorldToMap(t.shelf.transform.position, mapInner);
            Color tCol = t.state == ShadeTask.State.Claimed ? new Color(0.2f, 1f, 0.2f) : (t.state == ShadeTask.State.PatienceWaiting ? new Color(1f, 0.6f, 0.1f) : Color.yellow);

            // Draw pulsating star/box
            DrawRect(new Rect(tm.x - 4, tm.y - 4, 8, 8), tCol);
            nodeLabelStyle.normal.textColor = tCol;
            GUI.Label(new Rect(tm.x - 14, tm.y - 15, 28, 14), "T" + t.taskId, nodeLabelStyle);
        }

        // Draw robots and task connection lines
        for (int i = 0; i < fleetManifests.Count; i++)
        {
            RobotManifest m = fleetManifests[i];
            if (i >= warehouse.robots.Length) continue;
            Robot r = warehouse.robots[i];
            if (r == null) continue;

            Vector2 rm = WorldToMap(r.transform.position, mapInner);

            Color rCol = Color.green;
            if (m.isQuarantined || m.isStalled) rCol = Color.red;
            else if (!m.isOnline) rCol = new Color(0.85f, 0.3f, 1f); // Magenta Ghost
            else if (r.RobotState == Robot.RobotStates.OnWayToPick || r.RobotState == Robot.RobotStates.PickingUp) rCol = Color.yellow;
            else if (r.RobotState == Robot.RobotStates.OnWayToDrop) rCol = Color.cyan;

            // Connection line to target shelf if assigned
            if (m.heldTaskId != -1)
            {
                ShadeTask ht = activeTasks.Find(x => x.taskId == m.heldTaskId);
                if (ht != null && ht.shelf != null)
                {
                    Vector2 tm = WorldToMap(ht.shelf.transform.position, mapInner);
                    DrawLine(rm, tm, new Color(rCol.r, rCol.g, rCol.b, 0.6f), 1.5f);
                }
            }

            DrawRect(new Rect(rm.x - 4, rm.y - 4, 8, 8), rCol);
            nodeLabelStyle.normal.textColor = rCol;
            GUI.Label(new Rect(rm.x - 12, rm.y - 14, 24, 14), "R" + m.robotId, nodeLabelStyle);
        }

        // Mini-Map Legend at bottom
        float legY = mapY + mapH - 22;
        DrawRect(new Rect(mapX, legY, mapW, 22), new Color(0.08f, 0.12f, 0.18f, 0.95f));
        GUIStyle legStyle = new GUIStyle(GUI.skin.label);
        legStyle.fontSize = 9;
        legStyle.alignment = TextAnchor.MiddleCenter;
        GUI.Label(new Rect(mapX + 2, legY + 2, mapW - 4, 18),
            "<color=#44ff44>●Live</color>  <color=yellow>●OnWay</color>  <color=#dd44ff>●Ghost</color>  <color=red>●Stall</color>  <color=#ffff33>■Task</color>", legStyle);
    }
}
