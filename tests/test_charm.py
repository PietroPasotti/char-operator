# Copyright 2022 pietro
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import Mock

from charm import CharCharm
from ops.model import ActiveStatus, Network
from ops.testing import Harness


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(CharCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_war_action(self):
        # the harness doesn't (yet!) help much with actions themselves
        action_event = Mock(params={"fail": ""})
        self.harness.charm._on_war_action(action_event)

        self.assertTrue(action_event.set_results.called)

    def test_respawn_action(self):
        # the harness doesn't (yet!) help much with actions themselves
        action_event = Mock(params={"fail": ""})
        self.harness.charm._on_respawn_action(action_event)

        self.assertTrue(action_event.set_results.called)

    def test_config_changed(self):
        def get_plan():
            return self.harness.get_container_pebble_plan('char')

        plan = get_plan()
        self.assertEqual(plan.to_dict(), {})

        binding = Mock(
            network=Network(
                {
                    'bind-addresses': [
                        {
                            'interface-name': 'foo',
                            'addresses': [{'value': '0.0.0.0'}]
                        }
                    ]
                }
            )
        )
        self.harness.charm.model.get_binding = Mock(return_value=binding)

        self.harness.update_config({'enemies': '123;456'})

        plan = get_plan()
        expected = self.harness.charm._char_layer().to_dict()
        expected.pop('summary', '')
        expected.pop('description', '')

        self.assertEqual(plan.to_dict(), expected)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        container = self.harness.model.unit.get_container('char')
        self.assertTrue(container.get_service('char').is_running())
