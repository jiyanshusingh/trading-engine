from engines.indicator_engine import IndicatorEngine
from engines.swing_engine import SwingEngine
from engines.market_structure import MarketStructure
from engines.smc_engine import SMCEngine
from engines.structure_event_engine import StructureEventEngine
from engines.segment_engine import SegmentEngine
from engines.expansion_engine import ExpansionEngine
from assessments.market_configuration import MarketConfiguration
import pandas as pd
from policies.origin_region.ict_origin_region_policy import ICTOriginRegionPolicy
from engines.origin_region_engine import OriginRegionEngine
from engines.order_block_engine import OrderBlockEngine
from policies.order_block.ict.ict_order_block_candidate_generator import (
    ICTOrderBlockCandidateGenerator)
from policies.order_block.ict.ict_projection_policy import (
    ICTProjectionPolicy)
from engines.fair_value_gap_engine import (
    FairValueGapEngine)
from policies.fair_value_gap.ict.ict_fvg_policy import (
    ICTFairValueGapPolicy)
class MarketAnalysisEngine:
    def __init__(self):

        # Structure

        self.swing_engine = ...

        self.structure_engine = ...

        self.segment_engine = ...

        self.expansion_engine = ...

        # Regions

        self.origin_region_engine = ...

        self.order_block_engine = ...

        self.fvg_engine = ...

        self.liquidity_engine = ...

        # Relationships

        self.relationship_engine = ...

    def analyze(self, df):
        # Stage 0
        indicator_engine = IndicatorEngine()
        df = indicator_engine.calculate(df)

        # Stage 1
        swing_engine = SwingEngine(df)
        df = swing_engine.detect()
        
        # Stage 2
        market_structure = MarketStructure(df)
        df = market_structure.classify_structure()
        df = market_structure.detect_trend_candidate()
        df = market_structure.detect_protected_swings()
        df = market_structure.detect_bos()
        df = market_structure.detect_choch()
        
        # Market State
        market_structure = MarketStructure(df)
        df = market_structure.detect_market_state()

        # Stage 2
        structure_engine = StructureEventEngine(df)
        structure_events = structure_engine.generate_events()

        # Stage 3
        segment_engine = SegmentEngine(structure_events)
        segments = segment_engine.build()

        # Stage 4
        expansion_engine = ExpansionEngine(
            segments,
            structure_events
        )
        expansions = expansion_engine.build()
        
        configuration = MarketConfiguration(

            df=df,

            structure_events=tuple(structure_events),

            segments=tuple(segments),

            expansions=tuple(expansions)

        )
        origin_region_policy = ICTOriginRegionPolicy()

        origin_region_engine = OriginRegionEngine(

            expansions=expansions,

            configuration=configuration,

            policy=origin_region_policy

        )

        origin_regions = origin_region_engine.build()
        
        configuration = MarketConfiguration(

            df=df,

            structure_events=tuple(structure_events),

            segments=tuple(segments),

            expansions=tuple(expansions),

            origin_regions=tuple(origin_regions)

        )
        
        candidate_generator = ICTOrderBlockCandidateGenerator()

        projection_policy = ICTProjectionPolicy()

        order_block_engine = OrderBlockEngine(

            origin_regions=origin_regions,

            configuration=configuration,

            candidate_generator=candidate_generator,

            projection_policy=projection_policy

        )
        order_blocks = order_block_engine.build()
        
        # Fair Value Gaps
        fvg_policy = ICTFairValueGapPolicy()
        fvg_engine = FairValueGapEngine(
            configuration=configuration,
            policy=fvg_policy
        )
        fair_value_gaps = fvg_engine.build()

        # TODO
        # Liquidity Regions

        # TODO
        # Relationships

        # TODO
        # Market Configuration

        return MarketConfiguration(

            df=df,

            structure_events=tuple(structure_events),

            segments=tuple(segments),

            expansions=tuple(expansions),

            origin_regions=tuple(origin_regions),

            order_blocks=tuple(order_blocks),

            fair_value_gaps=tuple(fair_value_gaps),

            liquidity_regions=(),

            relationships=()

        )