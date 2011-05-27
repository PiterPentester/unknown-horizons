# ###################################################
# Copyright (C) 2011 The Unknown Horizons Team
# team@unknown-horizons.org
# This file is part of Unknown Horizons.
#
# Unknown Horizons is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################

import math
from Queue import Queue

from builder import Builder
from roadplanner import RoadPlanner

from horizons.ext.enum import Enum
from horizons.constants import BUILDINGS
from horizons.util import Point, Rect

class ProductionBuilder(object):
	purpose = Enum('branch_office', 'road', 'fisher', 'lumberjack', 'tree', 'reserved', 'none')

	def __init__(self, land_manager, branch_office):
		self.land_manager = land_manager
		self.island = land_manager.island
		self.session = self.island.session
		self.owner = self.land_manager.owner
		self.settlement = land_manager.settlement
		self.plan = dict.fromkeys(land_manager.production, (self.purpose.none, None))
		self.collector_buildings = [branch_office]
		for coords in branch_office.position.tuple_iter():
			if coords in self.plan:
				self.plan[coords] = (self.purpose.branch_office, None)

	def _get_neighbour_tiles(self, rect):
		"""
		returns the surrounding tiles except the corners
		"""
		moves = [(-1, 0), (0, -1), (0, 1), (1, 0)]
		for x, y in rect.tuple_iter():
			for dx, dy in moves:
				coords = (x + dx, y + dy)
				if not rect.contains_tuple(coords):
					yield self.island.get_tile_tuple(coords)

	def _get_possible_road_coords(self, rect):
		for tile in self._get_neighbour_tiles(rect):
			if tile is None:
				continue
			point = Point(tile.x, tile.y)
			building = self.session.world.get_building(point)
			if building is None:
				road = Builder(BUILDINGS.TRAIL_CLASS, self.land_manager, point)
				if road:
					yield (tile.x, tile.y)
			else:
				if building.id == BUILDINGS.TREE_CLASS or building.id == BUILDINGS.TRAIL_CLASS:
					yield (tile.x, tile.y)

	def _fill_distance(self, distance, nodes):
		moves = [(-1, 0), (0, -1), (0, 1), (1, 0)]
		queue = Queue()
		for item in distance.iteritems():
			queue.put(item)

		while not queue.empty():
			(coords, dist) = queue.get()
			for dx, dy in moves:
				coords2 = (coords[0] + dx, coords[1] + dy)
				if coords2 in nodes and coords2 not in distance:
					distance[coords2] = dist + 1
					queue.put((coords2, dist + 1))

	def _get_path_nodes(self):
		moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

		nodes = {}
		distance_to_road = {}
		distance_to_boundary = {}
		for coords in self.plan:
			if self.plan[coords][0] == self.purpose.none:
				nodes[coords] = 1
			elif self.plan[coords][0] == self.purpose.road:
				nodes[coords] = 1
				distance_to_road[coords] = 0

			for (dx, dy) in moves:
				coords2 = (coords[0] + dx, coords[1] + dy)
				if coords2 not in self.land_manager.production:
					distance_to_boundary[coords] = 1
					break

		for coords in self.land_manager.village:
			building = self.island.get_building(Point(coords[0], coords[1]))
			if building is not None and building.id == BUILDINGS.TRAIL_CLASS:
				nodes[coords] = 1
				distance_to_road[coords] = 0

		self._fill_distance(distance_to_road, self.island.path_nodes.nodes)
		self._fill_distance(distance_to_boundary, self.island.path_nodes.nodes)

		for coords in nodes:
			if coords in distance_to_road:
				distance = distance_to_road[coords]
				if distance > 9:
					nodes[coords] += 0.5
				elif 0 < distance <= 9:
					nodes[coords] += 0.7 + (10 - distance) * 0.07
			else:
				nodes[coords] += 0.1

			if coords in distance_to_boundary:
				distance = distance_to_boundary[coords]
				if 1 < distance <= 10:
					nodes[coords] += 0.3 + (11 - distance) * 0.03
			else:
				nodes[coords] += 0.1

		return nodes

	def _build_road_connection(self, builder):
		collector_coords = set()
		for building in self.collector_buildings:
			for coords in self._get_possible_road_coords(building.position):
				collector_coords.add(coords)

		blocked_coords = set([coords for coords in builder.position.tuple_iter()])
		destination_coords = set(self._get_possible_road_coords(builder.position))

		pos = builder.position
		beacon = Rect.init_from_borders(pos.left - 1, pos.top - 1, pos.right + 1, pos.bottom + 1)

		path = RoadPlanner()(collector_coords, destination_coords, beacon, self._get_path_nodes(), blocked_coords = blocked_coords)
		if path is not None:
			for x, y in path:
				point = Point(x, y)
				self.plan[point.to_tuple()] = (self.purpose.road, None)
				building = self.island.get_building(point)
				if building is not None and building.id == BUILDINGS.TRAIL_CLASS:
					continue
				road = Builder(BUILDINGS.TRAIL_CLASS, self.land_manager, point).execute()
		return path is not None

	def build_fisher(self):
		"""
		Finds a reasonable place for a fisher and builds the fisher and a road connection.
		"""
		options = []

		for (x, y), (purpose, _) in self.plan.iteritems():
			if purpose != self.purpose.none:
				continue
			point = Point(x, y)
			fisher = Builder(BUILDINGS.FISHERMAN_CLASS, self.land_manager, point)
			if not fisher or not self.land_manager.legal_for_production(fisher.position):
				continue

			fish_value = 0
			fishers_in_range = 1
			for tile in self.session.world.get_tiles_in_radius(point, 16):
				building = tile.object
				if building is None:
					continue
				if building.id == BUILDINGS.FISHERMAN_CLASS:
					fishers_in_range += 1
				elif building.id == BUILDINGS.FISH_DEPOSIT_CLASS:
					fish_value += 1.0 / math.log(point.distance_to_tuple((tile.x, tile.y)) + 2)
			if fish_value > 0:
				options.append((fishers_in_range / 1.0 / fish_value, fisher))

		for _, fisher in sorted(options):
			if not self._build_road_connection(fisher):
				continue
			fisher.execute()
			for coords in fisher.position.tuple_iter():
				self.plan[coords] = (self.purpose.reserved, None)
			self.plan[sorted(fisher.position.tuple_iter())[0]] = (self.purpose.fisher, fisher)
			return fisher
		return None

	def build_lumberjack(self):
		"""
		Finds a reasonable place for a lumberjack and builds the lumberjack along with
		a road connection and additional trees.
		"""
		moves = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
		options = []

		for (x, y), (purpose, _) in self.plan.iteritems():
			if purpose != self.purpose.none:
				continue
			point = Point(x, y)
			lumberjack = Builder(BUILDINGS.LUMBERJACK_CLASS, self.land_manager, point)
			if not lumberjack or not self.land_manager.legal_for_production(lumberjack.position):
				continue

			value = 0
			alignment = 0
			used_area = set(lumberjack.position.get_radius_coordinates(3, True))
			for coords in lumberjack.position.get_radius_coordinates(3):
				if coords not in self.plan:
					continue
				purpose = self.plan[coords][0]
				if purpose == self.purpose.none:
					value += 1
					for dx, dy in moves:
						coords2 = (coords[0] + dx, coords[1] + dy)
						if coords2 not in used_area:
							alignment += 1
				elif purpose == self.purpose.tree:
					value += 0.3
			value = min(value, 32)
			
			if value >= 10:
				options.append((-value - math.log(alignment + 1) - alignment / 5.0, lumberjack))

		for _, lumberjack in sorted(options):
			if not self._build_road_connection(lumberjack):
				continue
			lumberjack.execute()
			for coords in lumberjack.position.tuple_iter():
				self.plan[coords] = (self.purpose.reserved, None)
			self.plan[sorted(lumberjack.position.tuple_iter())[0]] = (self.purpose.lumberjack, lumberjack)
			
			for coords in lumberjack.position.get_radius_coordinates(3):
				if coords in self.plan and self.plan[coords][0] == self.purpose.none:
					self.plan[coords] = (self.purpose.tree, None)
					tree = Builder(BUILDINGS.TREE_CLASS, self.land_manager, Point(coords[0], coords[1])).execute()
			return lumberjack
		return None

	def display(self):
		road_colour = (30, 30, 30)
		fisher_colour = (128, 128, 128)
		lumberjack_colour = (30, 255, 30)
		tree_colour = (0, 255, 0)
		reserved_colour = (0, 0, 128)
		unknown_colour = (128, 0, 0)
		renderer = self.session.view.renderer['InstanceRenderer']

		for coords, (purpose, _) in self.plan.iteritems():
			tile = self.island.ground_map[coords]
			if purpose == self.purpose.road:
				renderer.addColored(tile._instance, *road_colour)
			elif purpose == self.purpose.fisher:
				renderer.addColored(tile._instance, *fisher_colour)
			elif purpose == self.purpose.lumberjack:
				renderer.addColored(tile._instance, *lumberjack_colour)
			elif purpose == self.purpose.tree:
				renderer.addColored(tile._instance, *tree_colour)
			elif purpose == self.purpose.reserved:
				renderer.addColored(tile._instance, *reserved_colour)
			else:
				renderer.addColored(tile._instance, *unknown_colour)
