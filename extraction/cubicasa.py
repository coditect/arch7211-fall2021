from collections import namedtuple
from functools import cached_property
from io import StringIO
from itertools import combinations
import math
import os.path
import re

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, split
import svgelements


id_pattern = re.compile("\s+id=\".*?\"", re.IGNORECASE)
display_none_pattern = re.compile("display\s*:\s*none\s*;", re.IGNORECASE)
whitespace = re.compile("\s+")

CLOSE_EDGE_TOLERANCE = 1.0
ROOM_TYPES = [
    "Alcove",
    "Attic",
    "Basement",
    "Bath",
    "Bedroom",
    "CarPort",
    "Closet",
    "Den",
    "Dining",
    "DraughtLobby",
    "DressingRoom",
    "Elevated",
    "Entry",
    "Garage",
    "Hall",
    "Kitchen",
    "Library",
    "LivingRoom",
    "Office",
    "Other",
    "Outdoor",
    "RecreationRoom",
    "Room",
    "Sauna",
    "Storage",
    "TechnicalRoom",
    "Undefined",
    "UserDefined",
    "Utility",
]

fixture_type_suffixes = re.compile("(Corner|High|Left|Low|Mid|Right|Round(Left|Right)?|Small|Triangle|2)$")
fixture_type_prefixes = re.compile("^(Corner|Double|Integrated|Gas|Wood|High|Round|Side)")

FIXTURE_TYPES = [
    "BaseCabinet",
    "Bathtub",
    "Chimney",
    "Closet",
    "CoatCloset",
    "CoatRack",
    "CounterTop",
    "Dishwasher",
    "ElectricalAppliance",
    "Fan",
    "Fireplace",
    "GEA",
    "Heater",
    "Housing",
    "Jacuzzi",
    "PlaceForFireplace",
    "Refrigerator",
    "SaunaBench",
    "SaunaStove",
    "Shower",
    "ShowerCab",
    "ShowerPlatform",
    "ShowerScreen",
    "Sink",
    "SpaceForAppliance",
    "Stove",
    "Toilet",
    "TumbleDryer",
    "Urinal",
    "WallCabinet",
    "WashingMachine",
    "WaterTap",
]

def simplify_fixture_type(classes):
    if classes[0] == "ElectricalAppliance" and len(classes) > 1:
        t = classes[1]
    else:
        t = classes[0]

    t = re.sub(fixture_type_prefixes, "", t)
    t = re.sub(fixture_type_suffixes, "", t)
    return t if t in FIXTURE_TYPES else "Other"


def get_classes(element):
    if svgelements.SVG_ATTR_CLASS in element.values:
        class_str = element.values[svgelements.SVG_ATTR_CLASS]
        return re.split(whitespace, class_str.strip())
    else:
        return []


def lines_are_close(line1, line2, tolerance):
    if line1.length > 0 and line2.length > 0:

        first_pair_found = False
        pairs = [
            (line1, line2.boundary[0]),
            (line1, line2.boundary[1]),
            (line2, line1.boundary[0]),
            (line2, line1.boundary[1])
        ]

        for edge, point in pairs:
            if edge.distance(point) < tolerance:
                if first_pair_found:
                    return True
                else:
                    first_pair_found = True

    return False

def polygon_edges(polygon):
    a = polygon.exterior.coords[:-1]
    b = polygon.exterior.coords[1:]
    return [LineString(points) for points in zip(a, b)]

def largest_polygon(polygons):
    largest = polygons[0]
    for p in polygons[1:]:
        if p.area > largest.area:
            largest = p
    return largest

def extend_or_append(list, iterable_or_not):
    try:
        list.extend(iterable_or_not)
    except:
        list.append(iterable_or_not)

def split_at_intersections(edges):
    split_edges = []

    for this_edge in edges:
        other_edges = MultiLineString([e for e in edges if e != this_edge])

        try:
            result = split(this_edge, other_edges)
        except:
            segments = []
            extend_or_append(segments, this_edge.intersection(other_edges))
            extend_or_append(segments, this_edge.difference(other_edges))
            result = [s for s in segments if isinstance(s, LineString) and not s.is_empty]

        split_edges.extend(result)

    return split_edges

def remove_duplicates(geometry_list):
    deduplicated = []

    for this in geometry_list:
        has_duplicate = False
        for that in deduplicated:
            if this.equals(that):
                has_duplicate = True
                break

        if not has_duplicate:
            deduplicated.append(this)

    return deduplicated

def polygon_from_points(points):
    num_points = len(points)

    if num_points == 0:
        return Point()

    if num_points == 1:
        return Point(points[0])

    if num_points == 2:
        return LineString(points)

    polygon = Polygon(points)
    if polygon.is_valid:
        return polygon

    raw_edges = polygon_edges(polygon)
    split_edges = split_at_intersections(raw_edges)
    deduplicated_edges = remove_duplicates(split_edges)
    polygons = list(polygonize(deduplicated_edges))

    if len(polygons) > 0:
        return largest_polygon(polygons)

    return Polygon()




class PlanObject:

    def __init__(self, container, index):
        self.container = container
        self.index = index
        self.adjacencies = AdjacencyList()

    def __repr__(self):
        return "{} {}".format(self.__class__.__name__, self.index)

    @property
    def polygon_element(self):
        return self.container[0]

    @cached_property
    def polygon(self):
        points = [Point(p.x, p.y) for p in self.polygon_element.points]
        return polygon_from_points(points)

    def num_edges(self):
        return len(self.polygon.exterior.coords) - 1

    def edges(self):
        return polygon_edges(self.polygon)

    def add_adjacency(self, object, intersection):
        self.adjacencies.add(object, intersection)

    def find_adjacencies(self, other_objects):
        for other in other_objects:
            intersection = self.polygon.intersection(other.polygon)
            if isinstance(intersection, LineString) or isinstance(intersection, MultiLineString):
                self.add_adjacency(other, intersection)
                other.add_adjacency(self, intersection)
            elif self._is_close(other):
                self.add_adjacency(other, None)
                other.add_adjacency(self, None)

    def _is_close(self, other):
        """Returns true if there is at least one pair of close edges between the two objects."""
        d = self.polygon.distance(other.polygon)
        if d <= CLOSE_EDGE_TOLERANCE:
            for self_edge in self.edges():
                for other_edge in other.edges():
                    if lines_are_close(self_edge, other_edge, CLOSE_EDGE_TOLERANCE):
                        return True

        return False


    def adjacencies_by_type(self, cls):
        return list(filter(lambda obj: isinstance(obj, cls), self.adjacencies.keys()))





class AdjacencyList(dict):

    def add(self, object, info):
        if object not in self:
            self[object] = []
        self[object].append(info)

    def filter(self, fn):
        matches = AdjacencyList()
        for object, info_list in self.items():
            for info_item in info_list:
                if fn(object, info_item):
                    matches.add(object, info_item)
        return matches




class Room(PlanObject):

    def __init__(self, container, index):
        super().__init__(container, index)
        self.doors = set()
        self.windows = set()
        self.fixtures = set()

    def __repr__(self):
        return "Room {} ({})".format(self.index, self.simple_type)

    @cached_property
    def types(self):
        classes = get_classes(self.container)
        return classes[1:] if len(classes) > 1 else []

    @property
    def full_type(self):
        return " ".join(self.types)

    @property
    def simple_type(self):
        return self.types[0] if self.types[0] in ROOM_TYPES else "Other"

    @property
    def is_outdoor(self):
        return self.types[0] == "Outdoor"

    def adjacent_walls(self):
        return self.adjacencies_by_type(Wall)

    def adjacent_exterior_walls(self):
        return list(filter(lambda w: w.is_exterior, self.adjacent_walls()))

    def adjacent_railings(self):
        return self.adjacencies_by_type(Railing)

    def adjacent_rooms(self):
        return self.adjacencies_by_type(Room)

    def connected_rooms(self):
        """Returns a list of rooms connected to this one via a door."""
        rooms = []
        for door in self.doors:
            if len(door.rooms) == 2:
                rooms.append(door.rooms[1] if door.rooms[0] == self else door.rooms[0])
        return rooms






class Divider(PlanObject):

    @property
    def eligible_edges(self):
        """Returns a list of edges that are eligible for adjacency checks.

        Most walls have exactly 4 edges.  The 0th and 2nd edges represent the faces of the wall and must be checked for
        adjacencies to rooms.  The 1st and 3rd edges represent the ends of the wall and do not need to be checked.  If a
        wall has fewer than 4 edges, it is considered degenerate and will not be checked at all.
        """
        if len(self.edges) == 4:
            return [self.edges[0], self.edges[2]]
        return []

    @property
    def eligible_edges_with_indexes(self):
        """Returns a list of edges that are eligible for adjacency checks along with their indexes in the main edges list."""
        return list(map(lambda e: (self.edges.index(e), e), self.eligible_edges))

    def rooms_opposite(self, room):
        """Returns a list of rooms adjacent to the opposite side of the wall/railing from the given room."""

        # This method does nothing right now.  It needs to be reimplemented to work with shapely.
        return []




class Railing(Divider):
    pass


class Wall(Divider):

    def __init__(self, container, index):
        super().__init__(container, index)
        self.openings = []
        self._polygon = None

        for child in container:
            if isinstance(child, svgelements.Group):
                object_type = get_classes(child)[0]
                if object_type == "Door":
                    self.openings.append(Door(self, child, len(self.openings)))
                elif object_type == "Window":
                    self.openings.append(Window(self, child, len(self.openings)))

    @property
    def polygon(self):
        if self._polygon == None:
            self._polygon = super().polygon
        return self._polygon

    @property
    def is_exterior(self):
        return "External" in get_classes(self.container)

    def add_adjacency(self, object, intersection):
        super().add_adjacency(object, intersection)

        if isinstance(object, Room):
            for opening in self.openings:
                opening.check_adjacencies(object)

    def remove_overlaps(self, other_wall, clean_overlaps_only=True):
        if self.polygon.relate_pattern(other_wall.polygon, "2121T1212"):

            self_difference = subtract_cleanly(self.polygon, other_wall.polygon, CLOSE_EDGE_TOLERANCE)
            if self_difference is not None:
                self._polygon = self_difference
                return True

            other_difference = subtract_cleanly(other_wall.polygon, self.polygon, CLOSE_EDGE_TOLERANCE)
            if other_difference is not None:
                other_wall._polygon = other_difference
                return True

            if clean_overlaps_only:
                return False

            other_wall._polygon = other_difference
            return True


def subtract_cleanly(this_polygon, that_polygon, tolerance):
    difference = this_polygon.difference(that_polygon)
    if isinstance(difference, Polygon):
        return difference

    if isinstance(difference, MultiPolygon) and len(difference) == 2:
        sizes = [minimum_rotated_rectangle_dimension(p) for p in difference]
        min_size = min(sizes)
        if min_size < tolerance:
            i = sizes.index(min_size)
            return difference[1-i]

def minimum_rotated_rectangle_dimension(polygon):
    rect = polygon.minimum_rotated_rectangle
    points = [Point(c) for c in rect.exterior.coords[:3]]
    d1 = points[0].distance(points[1])
    d2 = points[1].distance(points[2])
    return min(d1, d2)



class WallOpening(PlanObject):

    def __init__(self, wall, container, index):
        super().__init__(container, index)
        self.wall = wall
        self.rooms = []

        # The open sides of the wall opening polygon always have indicies 0 and 2.
        # They also match up with wall indices 0 and 2.

    def __repr__(self):
        return "{} in {}".format(super().__repr__(), self.wall)

    def check_adjacencies(self, room):
        if self.polygon.distance(room.polygon) < CLOSE_EDGE_TOLERANCE:
            self.add_adjacency(room)


class Door(WallOpening):

    def add_adjacency(self, room):
        self.rooms.append(room)
        room.doors.add(self)


class Window(WallOpening):

    def add_adjacency(self, room):
        self.rooms.append(room)
        room.windows.add(self)


class Fixture(PlanObject):

    def __init__(self, container, index):
        super().__init__(container, index)
        self.rooms = set()

    def __repr__(self):
        return "Fixture {} ({})".format(self.index, self.full_type)

    @property
    def polygon_element(self):
        for child in self.container:
            if isinstance(child, svgelements.Group):
            # if "#BoundaryPolygon" in get_classes(child):
                return child[0]

        # for child in self.container:
        # 	if "InnerPolygon" in get_classes(child):
        # 		return child[0]

        print(self.container.values)
        print(self.container.bbox())
        print(self.container[0].bbox())
        raise Exception("Boundary polygon not found")

    @cached_property
    def polygon(self):
        try:
            return super().polygon

        except Exception as err:
            e = self.polygon_element

            if isinstance(e, svgelements.Rect):
                return Polygon([
                    Point(e.x, e.y),
                    Point(e.x + e.width, e.y),
                    Point(e.x + e.width, e.y + e.height),
                    Point(e.x, e.y + e.height)
                ])

            if isinstance(e, svgelements.Circle):
                return Point(e.cx, e.cy).buffer(min(e.rx, e.ry))

            if isinstance(self.polygon_element, svgelements.Path):
                path_points = list(e.as_points())
                if len(path_points) >= 2 and path_points[0] == path_points[1]:
                    path_points = path_points[1:]

                if len(path_points) == 1:
                    return Point(path_points[0])

                # Should return LineString if the path is open and Polygon if the path is closed
                return LineString(path_points)

            raise Exception("Can't create polygon from", e)

    @cached_property
    def types(self):
        classes = get_classes(self.container)
        return classes[1:] if len(classes) > 1 else []

    @property
    def full_type(self):
        return " ".join(self.types)

    @property
    def simple_type(self):
        return simplify_fixture_type(self.types)

    def add_room(self, room, vertex=0):
        self.rooms.add(room)
        room.fixtures.add(self)

    def find_rooms(self, rooms):
        for room in rooms:
            if self.polygon.relate_pattern(room.polygon, "2********"):
                self.add_room(room)
                break


class Stair:

    def __init__(self, container, index):
        self.container = container
        self.index = index
        self.flights = []
        self.windings = []

    def __repr__(self):
        return "Stair {}".format(self.index)


class StairFlight(PlanObject):
    pass


class StairWinding(PlanObject):
    pass








def find_children_by_class(parent, class_name):
    try:
        return list(filter(lambda child: class_name in get_classes(child), parent))
    except:
        return []


class PlanObjectList(list):

    def __init__(self, object_class, *args, **kwargs):
        super().__init__(self, *args, **kwargs)
        self.object_class = object_class

    def add(self, object):
        self.append(self.object_class(object, len(self)))


class Model:

    def __init__(self, file):
        self.document = svgelements.SVG.parse(file)
        self.model = find_children_by_class(self.document, "Model")[0]
        self.floors = []

        for child in find_children_by_class(self.model, "Floor"):
            self.floors.append(Floor(child))


class Floor:

    def __init__(self, container):
        self.container = container
        self.rooms = PlanObjectList(Room)
        self.walls = PlanObjectList(Wall)
        self.railings = PlanObjectList(Railing)
        self.fixtures = PlanObjectList(Fixture)

    def find_objects(self):
        plan = find_children_by_class(self.container, "Floorplan")[0]

        for child in plan:
            if isinstance(child, svgelements.Group):
                object_type = get_classes(child)[0]

                if object_type == "Space":
                    self.rooms.add(child)

                elif object_type == "Wall":
                    self.walls.add(child)

                elif object_type == "Railing":
                    self.railings.add(child)

                elif object_type == "FixedFurniture":
                    self.fixtures.add(child)

                elif object_type == "FixedFurnitureSet":
                    for grandchild in child:
                        self.fixtures.add(grandchild)

    def area(self):
        """Returns the total area of the floor."""
        area = 0

        for room in self.rooms:
            area += room.polygon.area

        for wall in self.walls:
            area += wall.polygon.area

        return area

    def remove_wall_overlaps(self):
        """Adjusts walls in the model so none of them overlap."""
        pairs = list(combinations(self.walls, 2))
        pairs_to_retry = []

        while True:

            # Any pairs that can't be differenced cleanly go into pairs_to_retry
            for this_wall, that_wall in pairs:
                if this_wall.remove_overlaps(that_wall) == False:
                    pairs_to_retry.append((this_wall, that_wall))

            # If there are no pairs to retry, we're done
            if len(pairs_to_retry) == 0:
                return

            # If we have just as many pairs to retry as we started with, exit the loop
            if len(pairs_to_retry) == len(pairs):
                break

            # Go again
            pairs = pairs_to_retry
            pairs_to_retry = []

        # Any overlaps that are left at this point can't be differenced cleanly
        for this_wall, that_wall in pairs_to_retry:
            this_wall.remove_overlaps(that_wall, clean_overlaps_only=False)

    def find_adjacencies(self):
        self.remove_wall_overlaps()
        for room_index, room in enumerate(self.rooms):
            room.find_adjacencies(self.walls)
            room.find_adjacencies(self.railings)
            room.find_adjacencies(self.rooms[room_index+1:])

    def find_inside(self):
        for fixture in self.fixtures:
            fixture.find_rooms(self.rooms)




class Cubicasa:

    def __init__(self, basepath):
        self.basepath = basepath

    def get_model(self, *path):
        model_path = os.path.join(self.basepath, *path, "model.svg")
        with open(model_path) as file:
            contents = file.read()

            # Strip out all id attributes
            contents = re.sub(id_pattern, " ", contents)

            # Strip out all "display: none" styles -- they cause svgelements to ignore
            contents = re.sub(display_none_pattern, " ", contents)

            # Some models have invalid <path> data that causes svgelements to ignore the affected elements
            # See high_quality_architectural/10074/model.svg for examples
            contents = contents.replace("LNaN,NaN", "")

            model = Model(StringIO(contents))
            model.path = model_path
            return model

    def paths(self):
        parent_folders = [ f.name for f in os.scandir(self.basepath) if f.is_dir()]
        for p in parent_folders:
            path = os.path.join(self.basepath, p)
            child_folders = [ f.name for f in os.scandir(path) if f.is_dir() ]
            for c in child_folders:
                yield (p, c)

    def models(self, limit=None, offset=0):
        limit_count = 0
        offset_count = 0

        for path in self.paths():
            if offset > offset_count:
                offset_count += 1

            elif limit is None or limit > limit_count:
                yield self.get_model(*path)
                limit_count += 1

            else:
                break
