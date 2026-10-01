using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
using UnityEngine;

public class Builder
{
    public static void BuildLinux()
    {
        var scene = EditorSceneManager.OpenScene("Assets/Scenes/Main.unity");
        EditorSceneManager.SaveScene(scene);
        AssetDatabase.SaveAssets();

        var shelves = Object.FindObjectsByType<Warehouse_shelf>(FindObjectsInactive.Include, FindObjectsSortMode.None);
        Debug.Log("Total shelves in scene: " + shelves.Length);

        string[] scenes = new string[] { "Assets/Scenes/Main.unity" };
        string buildPath = "Builds/Linux/WarehouseSimulation.x86_64";
        
        BuildPlayerOptions buildPlayerOptions = new BuildPlayerOptions();
        buildPlayerOptions.scenes = scenes;
        buildPlayerOptions.locationPathName = buildPath;
        buildPlayerOptions.target = BuildTarget.StandaloneLinux64;
        buildPlayerOptions.options = BuildOptions.None;

        BuildReport report = BuildPipeline.BuildPlayer(buildPlayerOptions);
        BuildSummary summary = report.summary;

        if (summary.result == BuildResult.Succeeded)
        {
            Debug.Log("Build succeeded: " + summary.totalSize + " bytes");
            EditorApplication.Exit(0);
        }
        else
        {
            Debug.LogError("Build failed: " + summary.result);
            EditorApplication.Exit(1);
        }
    }
}
