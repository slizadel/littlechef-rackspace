from StringIO import StringIO
import unittest
from libcloud.compute.base import NodeImage, NodeSize, Node
from libcloud.compute.types import Provider, NodeState
import mock
from littlechef_rackspace.api import RackspaceApi, Regions
from littlechef_rackspace.lib import Host


class RackspaceApiTest(unittest.TestCase):
    def setUp(self):
        self.username = 'username'
        self.apikey = 'deadbeef'

        self.pending_node = Node(id='id', name='name', public_ips=[], private_ips=[],
                                 state=NodeState.PENDING, driver=None)
        self.active_node = Node(id='id', name='name', public_ips=[ '50.2.3.4'], private_ips=[],
                                state=NodeState.RUNNING, driver=None)


    def test_list_images_instantiates_driver_with_user_and_password(self):
        with mock.patch("littlechef_rackspace.api.get_driver") as get_driver:
            driver = get_driver.return_value

            api = self._get_api(Regions.DFW)
            api.list_images()

            driver.assert_any_call(self.username, self.apikey)

    def test_list_images_instantiates_dfw_driver(self):
        with mock.patch("littlechef_rackspace.api.get_driver") as get_driver:
            api = self._get_api(Regions.DFW)
            api.list_images()

        get_driver.assert_any_call(Provider.RACKSPACE_NOVA_DFW)

    def test_list_images_instantiates_ord_driver(self):
        with mock.patch("littlechef_rackspace.api.get_driver") as get_driver:
            api = self._get_api(Regions.ORD)
            api.list_images()

            get_driver.assert_any_call(Provider.RACKSPACE_NOVA_ORD)

    def _get_api_with_mocked_conn(self, conn):
        api = self._get_api(Regions.ORD)
        api._get_conn = mock.Mock(return_value=conn)
        return api

    def test_list_images_returns_image_information(self):
        conn = mock.Mock()
        api = self._get_api_with_mocked_conn(conn)

        lc_image1 = NodeImage('abc-def', 'Image 1', None)
        lc_image2 = NodeImage('fge-hgi', 'Image 2', None)

        conn.list_images.return_value = [lc_image1, lc_image2]

        self.assertEquals([{
                               'id': lc_image1.id,
                               'name': lc_image1.name
                           }, {
                               'id': lc_image2.id,
                               'name': lc_image2.name
                           }], api.list_images())

    def test_creates_node(self):
        conn = mock.Mock()
        api = self._get_api_with_mocked_conn(conn)

        image_id = "5cebb13a-f783-4f8c-8058-c4182c724ccd"
        flavor_id = "2"
        node_name = "new-node"
        public_key = "ssh-file deadbeef dave@isis"
        public_key_io = StringIO(public_key)
        conn.create_node.return_value = self.active_node

        api.create_node(node_name=node_name,
                        image_id=image_id,
                        flavor_id=flavor_id,
                        public_key_io=public_key_io)

        call_kwargs = conn.create_node.call_args_list[0][1]
        self.assertEquals(node_name, call_kwargs['name'])
        self.assertEquals(image_id, call_kwargs['image'].id)
        self.assertEquals(flavor_id, call_kwargs['size'].id)
        self.assertEquals({"/root/.ssh/authorized_keys": public_key},
                          call_kwargs['ex_files'])

    def test_waits_for_node_to_become_active(self):
        conn = mock.Mock()
        api = self._get_api_with_mocked_conn(conn)

        conn.create_node.return_value = self.pending_node
        conn.ex_get_node_details.return_value = self.active_node

        with mock.patch('littlechef_rackspace.api.time') as time:
            api.create_node(node_name="some name",
                            image_id="5cebb13a-f783-4f8c-8058-c4182c724ccd",
                            flavor_id="2",
                            public_key_io=StringIO("some public key"))
            time.sleep.assert_any_call(5)

    def test_returns_host_information(self):
        conn = mock.Mock()
        api = self._get_api_with_mocked_conn(conn)

        public_ipv4_address = "50.51.52.53"
        self.active_node.public_ips = [
            "2222::2222:2",
            public_ipv4_address
        ]
        self.active_node.extra['password'] = 'password'
        conn.create_node.return_value = self.active_node

        result = api.create_node(node_name="some name",
                                 image_id="5cebb13a-f783-4f8c-8058-c4182c724ccd",
                                 flavor_id="2",
                                 public_key_io=StringIO("some public key"))

        self.assertEquals(result, Host(name="some name",
                                       host_string=public_ipv4_address,
                                       password="password"))

    def test_outputs_progress_during_creation(self):
        conn = mock.Mock()
        api = self._get_api_with_mocked_conn(conn)

        progress = StringIO()

        conn.create_node.return_value = self.pending_node

        self.counter = 0
        def ex_get_node_details(id):
            if self.counter == 5:
                return self.active_node

            self.counter += 1
            return self.pending_node

        conn.ex_get_node_details.side_effect = ex_get_node_details
        password = 'abcDEFghiJKL'
        self.pending_node.extra['password'] = password

        with mock.patch('littlechef_rackspace.api.time') as time:
            node_name = "new node"
            image_id = "dontcare"
            flavor_id = "2"
            host = api.create_node(node_name=node_name, image_id=image_id,
                                   flavor_id=flavor_id, public_key_io=StringIO("some key"),
                                   progress=progress)

            self.assertEquals([
                "Creating node {0} (image: {1}, flavor: {2})...".format(node_name, image_id, flavor_id),
                "Created node {0} (id: {1}, password: {2})".format(node_name, self.pending_node.id, password),
                "Waiting for node to become active{0}".format("." * 6),
                "Node active! (host: {0})".format(host.host_string)
            ], progress.getvalue().splitlines())

    def _get_api(self, region):
        return RackspaceApi(self.username, self.apikey, region)