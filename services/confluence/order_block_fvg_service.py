from models.order_block_fvg_overlap import OrderBlockFVGOverlap


class OrderBlockFVGService:

    def find_overlaps(
        self,
        order_blocks,
        fair_value_gaps
    ):

        overlaps = []

        for order_block in order_blocks:

            for fvg in fair_value_gaps:

                if (
                    order_block.low <= fvg.upper_price
                    and
                    fvg.lower_price <= order_block.high
                ):

                    overlaps.append(

                        OrderBlockFVGOverlap(
                            order_block=order_block,
                            fair_value_gap=fvg
                        )

                    )

        return overlaps