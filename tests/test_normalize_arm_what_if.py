import unittest

from scripts.normalize_arm_what_if import normalize_what_if


class NormalizeArmWhatIfTests(unittest.TestCase):
    def test_known_server_defaults_and_runtime_roles_are_normalized(self):
        report = normalize_what_if(
            {
                "changes": [
                    {
                        "changeType": "Modify",
                        "resourceId": "/providers/Microsoft.Network/privateEndpoints/pe",
                        "after": {"type": "Microsoft.Network/privateEndpoints"},
                        "delta": [
                            {
                                "path": "properties.isIPv6EnabledPrivateEndpoint",
                                "propertyChangeType": "Delete",
                            },
                            {
                                "path": "properties.subnet.id",
                                "propertyChangeType": "Modify",
                            },
                        ],
                    },
                    {
                        "changeType": "Unsupported",
                        "resourceId": (
                            "[extensionResourceId('/providers/Microsoft.Storage/"
                            "storageAccounts/demo', 'Microsoft.Authorization/"
                            "roleAssignments', guid(reference('identity').principalId,"
                            "'ba92f5b4-2d11-453d-a403-e96b0029c9fe'))]"
                        ),
                    },
                ]
            }
        )
        self.assertTrue(report["noEffectiveChanges"])
        self.assertEqual(report["effectiveChangeCount"], 0)
        self.assertEqual(report["normalizedNoiseCount"], 2)

    def test_unknown_property_fails_closed(self):
        report = normalize_what_if(
            {
                "changes": [
                    {
                        "changeType": "Modify",
                        "resourceId": "/providers/Microsoft.Network/privateEndpoints/pe",
                        "after": {"type": "Microsoft.Network/privateEndpoints"},
                        "delta": [
                            {
                                "path": "properties.publicNetworkAccess",
                                "propertyChangeType": "Modify",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertFalse(report["noEffectiveChanges"])
        self.assertEqual(
            report["effectiveChanges"][0]["unknownPaths"],
            ["properties.publicNetworkAccess"],
        )

    def test_create_delete_and_unknown_unsupported_fail_closed(self):
        for change in (
            {"changeType": "Create", "resourceId": "/resource/new"},
            {"changeType": "Delete", "resourceId": "/resource/old"},
            {"changeType": "Unsupported", "resourceId": "/resource/unknown"},
        ):
            with self.subTest(change=change):
                self.assertFalse(
                    normalize_what_if({"changes": [change]})["noEffectiveChanges"]
                )

    def test_no_effect_on_unknown_type_and_path_fails_closed(self):
        report = normalize_what_if(
            {
                "changes": [
                    {
                        "changeType": "Modify",
                        "resourceId": "/providers/Microsoft.Example/widgets/widget",
                        "after": {"type": "Microsoft.Example/widgets"},
                        "delta": [
                            {
                                "path": "properties.generatedDefault",
                                "propertyChangeType": "NoEffect",
                            }
                        ],
                    }
                ]
            }
        )
        self.assertFalse(report["noEffectiveChanges"])


if __name__ == "__main__":
    unittest.main()
